import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from sqlalchemy import create_engine, MetaData, text, Column, Integer, String, DateTime, Boolean, UniqueConstraint
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

# Import PostgreSQLSpaceImpl for RDF space management
from .postgresql_space_impl import PostgreSQLSpaceImpl

# Create declarative base for ORM models
Base = declarative_base()


def create_models_with_prefix(prefix: str):
    """
    Create SQLAlchemy ORM models with the specified table prefix.
    Uses caching to prevent duplicate model creation.
    
    Args:
        prefix (str): Table prefix to use (e.g., 'vitalgraph1_')
        
    Returns:
        tuple: (Install, Space, User) model classes
    """
    # Check cache first
    if prefix in _model_cache:
        return _model_cache[prefix]
    
    class Install(Base):
        """
        SQLAlchemy ORM model for Install table.
        
        Tracks initialization state and metadata for a VitalGraph installation.
        Only one Install record should be active at a time.
        """
        __tablename__ = f'{prefix}install'
        __table_args__ = {'extend_existing': True}
        
        id = Column(Integer, primary_key=True, autoincrement=True)
        install_datetime = Column(DateTime, default=datetime.utcnow, nullable=False)
        update_datetime = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
        active = Column(Boolean, default=True, nullable=False)
        
        def __repr__(self):
            return f"<Install(id={self.id}, install_datetime='{self.install_datetime}', active={self.active})>"
        
        def to_dict(self) -> Dict[str, Any]:
            """Convert Install instance to dictionary."""
            return {
                'id': self.id,
                'install_datetime': self.install_datetime.isoformat() if self.install_datetime else None,
                'update_datetime': self.update_datetime.isoformat() if self.update_datetime else None,
                'active': self.active
            }
    
    class Space(Base):
        """
        SQLAlchemy ORM model for Space table.
        
        Represents a graph space with tenant isolation.
        """
        __tablename__ = f'{prefix}space'
        __table_args__ = (
            UniqueConstraint('space', name=f'uq_{prefix}space_space'),  # space field must be unique
            {'extend_existing': True}
        )
        
        id = Column(Integer, primary_key=True, autoincrement=True)
        tenant = Column(String(255), nullable=True)  # Optional
        space = Column(String(255), nullable=False, unique=True)  # Required and unique
        space_name = Column(String(255), nullable=False)  # Required
        space_description = Column(String(255), nullable=True)  # Optional
        update_time = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
        
        def __repr__(self):
            return f"<Space(id={self.id}, tenant='{self.tenant}', space='{self.space}', name='{self.space_name}')>"
        
        def to_dict(self) -> Dict[str, Any]:
            """Convert Space instance to dictionary."""
            return {
                'id': self.id,
                'tenant': self.tenant,
                'space': self.space,
                'space_name': self.space_name,
                'space_description': self.space_description,
                'update_time': self.update_time.isoformat() if self.update_time else None
            }
    
    class User(Base):
        """
        SQLAlchemy ORM model for User table.
        
        Represents a user with tenant isolation and authentication info.
        """
        __tablename__ = f'{prefix}user'
        __table_args__ = (
            UniqueConstraint('username', name=f'uq_{prefix}user_username'),  # username must be unique
            UniqueConstraint('email', name=f'uq_{prefix}user_email'),        # email must be unique
            {'extend_existing': True}
        )
        
        id = Column(Integer, primary_key=True, autoincrement=True)
        tenant = Column(String(255), nullable=True)  # Optional
        username = Column(String(255), nullable=False, unique=True)  # Required and unique
        password = Column(String(255), nullable=False)  # Required (should be hashed)
        email = Column(String(255), nullable=False, unique=True)  # Required and unique
        update_time = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
        
        def __repr__(self):
            return f"<User(id={self.id}, tenant='{self.tenant}', username='{self.username}', email='{self.email}')>"
        
        def to_dict(self) -> Dict[str, Any]:
            """Convert User instance to dictionary."""
            return {
                'id': self.id,
                'tenant': self.tenant,
                'username': self.username,
                'password': self.password,
                'email': self.email,
                'update_time': self.update_time.isoformat() if self.update_time else None
            }
    
    # Cache the models before returning
    _model_cache[prefix] = (Install, Space, User)
    return Install, Space, User


# Model cache to prevent duplicate creation
_model_cache = {}

# Default models (will be replaced by create_models_with_prefix)
Install = None
Space = None
User = None


class PostgreSQLDbImpl:
    """
    PostgreSQL database implementation for VitalGraph.
    
    Centralizes all database functionality including connection management,
    table operations, user management, and space management.
    """
    
    def __init__(self, config: Dict[str, Any], tables_config: Dict[str, Any] = None):
        """
        Initialize PostgreSQL database implementation.
        
        Args:
            config: Database configuration dictionary containing connection parameters
            tables_config: Tables configuration dictionary containing table prefix
        """
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.config = config
        self.tables_config = tables_config or {}
        self.engine = None
        self.session_factory = None
        self.metadata = None
        self.connected = False
        
        # State management
        self.state = "disconnected"  # disconnected, uninitialized, initialized
        self.table_prefix = self.tables_config.get('prefix', 'vg_')
        self.current_install = None
        self.current_spaces = []
        self.current_users = []
        
        # Initialize models with prefix
        global Install, Space, User
        Install, Space, User = create_models_with_prefix(self.table_prefix)
        self.Install = Install
        self.Space = Space
        self.User = User
        
        # Initialize PostgreSQLSpaceImpl for RDF space management
        # Extract global prefix from table prefix (remove trailing underscore)
        global_prefix = self.table_prefix.rstrip('_')
        self.space_impl = None  # Will be initialized after engine is created
        self.global_prefix = global_prefix
        
        self.logger.info(f"PostgreSQLDbImpl initialized with config: {self._sanitize_config_for_logging(config)}")
        self.logger.info(f"Table prefix: {self.table_prefix}")
        self.logger.info(f"Global prefix for RDF spaces: {self.global_prefix}")
    
    def _sanitize_config_for_logging(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Remove sensitive information from config for logging."""
        sanitized = config.copy()
        if 'password' in sanitized:
            sanitized['password'] = '***'
        return sanitized
    
    async def connect(self) -> bool:
        """
        Connect to database and populate state.
        
        Looks for existence of install, space, and user tables and loads current state.
        If not found, state is set to "uninitialized".
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            self.logger.info("Connecting to PostgreSQL database...")
            
            # Build database URL
            db_url = self._build_database_url()
            
            # Create engine
            self.engine = create_engine(
                db_url,
                pool_size=self.config.get('pool_size', 10),
                max_overflow=self.config.get('max_overflow', 20),
                pool_timeout=self.config.get('pool_timeout', 30),
                pool_recycle=self.config.get('pool_recycle', 3600)
            )
            
            # Create session factory
            self.session_factory = sessionmaker(bind=self.engine)
            
            # Use ORM metadata from Base
            self.metadata = Base.metadata
            
            # Test connection
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT 1"))
                self.logger.info(f"Database connection test successful: {result.scalar()}")
            
            self.connected = True
            
            # Initialize PostgreSQLSpaceImpl with connection string and config
            connection_string = f"postgresql://{self.config['username']}:{self.config['password']}@{self.config['host']}:{self.config['port']}/{self.config['database']}"
            use_unlogged = self.tables_config.get('use_unlogged', True)  # Default to True for performance
            
            self.space_impl = PostgreSQLSpaceImpl(connection_string=connection_string, global_prefix=self.global_prefix, use_unlogged=use_unlogged)
            self.logger.info(f"PostgreSQLSpaceImpl initialized with global prefix: {self.global_prefix}")
            
            # Load current state from database
            await self._load_current_state()
            
            self.logger.info(f"Successfully connected to PostgreSQL database - State: {self.state}")
            return True
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database connection failed: {e}")
            self.connected = False
            self.state = "disconnected"
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error during database connection: {e}")
            self.connected = False
            self.state = "disconnected"
            return False
    
    async def _load_current_state(self) -> None:
        """
        Load current state from database by checking for install, space, and user tables.
        
        Sets state to "uninitialized" if no active install found, "initialized" otherwise.
        """
        try:
            self.logger.info("Loading current state from database...")
            
            # Check if tables exist by trying to query them
            with self.session_factory() as session:
                try:
                    # Try to find active install
                    active_install = session.query(self.Install).filter(
                        self.Install.active == True
                    ).first()
                    
                    if active_install:
                        self.current_install = active_install.to_dict()
                        
                        # Load spaces and users
                        spaces = session.query(self.Space).all()
                        self.current_spaces = [space.to_dict() for space in spaces]
                        
                        users = session.query(self.User).all()
                        self.current_users = [user.to_dict() for user in users]
                        
                        self.state = "initialized"
                        self.logger.info(f"Loaded initialized state: Install ID {active_install.id}, {len(self.current_spaces)} spaces, {len(self.current_users)} users")
                    else:
                        self.state = "uninitialized"
                        self.current_install = None
                        self.current_spaces = []
                        self.current_users = []
                        self.logger.info("No active install found - state is uninitialized")
                        
                except SQLAlchemyError as e:
                    # Tables probably don't exist
                    self.state = "uninitialized"
                    self.current_install = None
                    self.current_spaces = []
                    self.current_users = []
                    self.logger.info(f"Tables not found or error querying: {e} - state is uninitialized")
                    
        except Exception as e:
            self.logger.error(f"Error loading current state: {e}")
            self.state = "uninitialized"
            self.current_install = None
            self.current_spaces = []
            self.current_users = []
    
    async def disconnect(self) -> None:
        """
        Disconnect from database and clear state.
        
        Disconnects and unloads the state, putting things into disconnected state.
        """
        try:
            self.logger.info("Disconnecting from PostgreSQL database...")
            
            if self.engine:
                self.engine.dispose()
                self.engine = None
            
            # Clean up PostgreSQLSpaceImpl instance
            self.space_impl = None
            
            self.session_factory = None
            self.metadata = None
            self.connected = False
            
            # Clear state
            self.state = "disconnected"
            self.current_install = None
            self.current_spaces = []
            self.current_users = []
            
            self.logger.info("Successfully disconnected from PostgreSQL database and cleared state")
            
        except Exception as e:
            self.logger.error(f"Error during database disconnection: {e}")
    
    async def refresh(self) -> bool:
        """
        Reconnect to database and refresh state.
        
        Refreshes the connection and reloads state, moving out of disconnected state.
        
        Returns:
            True if refresh successful, False otherwise
        """
        self.logger.info("Refreshing database connection and state...")
        await self.disconnect()
        success = await self.connect()
        if success:
            self.logger.info(f"Database refresh completed - State: {self.state}")
        return success
    
    def get_space_impl(self) -> Optional['PostgreSQLSpaceImpl']:
        """
        Get the PostgreSQLSpaceImpl instance for RDF space management.
        
        Returns:
            PostgreSQLSpaceImpl instance if connected, None otherwise
        """
        if not self.connected or self.space_impl is None:
            self.logger.warning("PostgreSQLSpaceImpl not available - database not connected")
            return None
        
        return self.space_impl
    
    def _build_database_url(self) -> URL:
        """
        Build PostgreSQL database URL from configuration.
        
        Returns:
            SQLAlchemy URL object for database connection
        """
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.config.get('username', 'vitalgraph_user'),
            password=self.config.get('password', 'vitalgraph_password') or None,
            host=self.config.get('host', 'localhost'),
            port=self.config.get('port', 5432),
            database=self.config.get('database', 'vitalgraphdb'),
        )
    
    # Database management methods
    async def init_tables(self) -> bool:
        """
        Initialize database tables and create initial install record.
        
        Creates tables with one install object and zero spaces and users,
        but only if in the uninitialized state.
        
        Returns:
            True if initialization successful, False otherwise
        """
        try:
            self.logger.info("Initializing database tables...")
            
            if not self.connected or not self.engine:
                self.logger.error("Not connected to database")
                return False
            
            if self.state != "uninitialized":
                self.logger.warning(f"Cannot initialize - current state is '{self.state}', must be 'uninitialized'")
                return False
            
            # Create all ORM tables (Install, Space, User) if they don't exist
            Base.metadata.create_all(self.engine, checkfirst=True)
            
            # Create initial install record
            with self.session_factory() as session:
                new_install = self.Install(
                    install_datetime=datetime.utcnow(),
                    active=True
                )
                session.add(new_install)
                session.commit()
                
                self.current_install = new_install.to_dict()
                self.current_spaces = []
                self.current_users = []
                self.state = "initialized"
                
                self.logger.info(f"Database tables initialized successfully with Install ID: {new_install.id}")
                return True
            
        except SQLAlchemyError as e:
            self.logger.error(f"Failed to initialize database tables: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error during table initialization: {e}")
            return False
    
    async def purge_tables(self) -> bool:
        """
        Reset all tables to initial state.
        
        Returns:
            True if purge successful, False otherwise
        """
        try:
            self.logger.info("Purging database tables...")
            
            if not self.connected or not self.session_factory:
                self.logger.error("Not connected to database")
                return False
            
            with self.session_factory() as session:
                # Delete all users and spaces, but keep install record
                session.query(self.User).delete()
                session.query(self.Space).delete()
                session.commit()
                
                # Reload state
                await self._load_current_state()
                
                self.logger.info("Database tables purged successfully")
                return True
                
        except SQLAlchemyError as e:
            self.logger.error(f"Failed to purge database tables: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error during table purging: {e}")
            return False
    
    async def destroy(self) -> bool:
        """
        Destroy current installation and recreate fresh state.
        
        Sets the install to inactive, removes the space and user tables/objects,
        recreates the space/user tables/objects, and adds a new install record that is active.
        
        Returns:
            True if destroy successful, False otherwise
        """
        try:
            self.logger.info("Destroying current installation...")
            
            if not self.connected or not self.session_factory:
                self.logger.error("Not connected to database")
                return False
            
            with self.session_factory() as session:
                # Set current install to inactive
                if self.current_install:
                    current_install = session.query(self.Install).filter(
                        self.Install.id == self.current_install['id']
                    ).first()
                    if current_install:
                        current_install.active = False
                        current_install.update_datetime = datetime.utcnow()
                
                # Delete all users and spaces
                session.query(self.User).delete()
                session.query(self.Space).delete()
                
                # Create new active install
                new_install = self.Install(
                    install_datetime=datetime.utcnow(),
                    active=True
                )
                session.add(new_install)
                session.commit()
                
                # Update state
                self.current_install = new_install.to_dict()
                self.current_spaces = []
                self.current_users = []
                self.state = "initialized"
                
                self.logger.info(f"Installation destroyed and recreated with new Install ID: {new_install.id}")
                return True
                
        except SQLAlchemyError as e:
            self.logger.error(f"Failed to destroy installation: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error during installation destroy: {e}")
            return False
    
    async def delete_tables(self) -> bool:
        """
        Delete all VitalGraphDB tables (install, space, user).
        
        Completely removes all tables and sets state to uninitialized.
        
        Returns:
            True if deletion successful, False otherwise
        """
        try:
            self.logger.info("Deleting all database tables...")
            
            if not self.connected or not self.engine:
                self.logger.error("Not connected to database")
                return False
            
            # Drop all ORM tables
            Base.metadata.drop_all(self.engine, checkfirst=True)
            
            # Clear state
            self.current_install = None
            self.current_spaces = []
            self.current_users = []
            self.state = "uninitialized"
            
            self.logger.info("All database tables deleted successfully")
            return True
            
        except SQLAlchemyError as e:
            self.logger.error(f"Failed to delete database tables: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error during table deletion: {e}")
            return False
    
    async def get_database_info(self) -> Dict[str, Any]:
        """
        Show database information including current state.
        
        Returns:
            Dictionary containing database information and current state
        """
        self.logger.info("Getting database information...")
        return {
            "connected": self.connected,
            "state": self.state,
            "database": self.config.get('database', 'unknown'),
            "host": self.config.get('host', 'unknown'),
            "port": self.config.get('port', 'unknown'),
            "table_prefix": self.table_prefix,
            "current_install": self.current_install,
            "spaces_count": len(self.current_spaces),
            "users_count": len(self.current_users)
        }
    
    # Install management methods (internal use only)
    async def _list_installs(self) -> List[Dict[str, Any]]:
        """
        List all install records (internal use only).
        
        Returns:
            List of install dictionaries
        """
        try:
            self.logger.info("Listing install records...")
            
            if not self.connected or not self.session_factory:
                self.logger.error("Not connected to database")
                return []
            
            with self.session_factory() as session:
                installs = session.query(self.Install).all()
                result = [install.to_dict() for install in installs]
                
                self.logger.info(f"Found {len(result)} install records")
                return result
                
        except SQLAlchemyError as e:
            self.logger.error(f"Database error listing installs: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Unexpected error listing installs: {e}")
            return []
    
    async def _get_active_install(self) -> Optional[Dict[str, Any]]:
        """
        Get the currently active install record (internal use only).
        
        Returns:
            Active install dictionary or None
        """
        try:
            self.logger.info("Getting active install record...")
            
            if not self.connected or not self.session_factory:
                self.logger.error("Not connected to database")
                return None
            
            with self.session_factory() as session:
                active_install = session.query(self.Install).filter(
                    self.Install.active == True
                ).first()
                
                if active_install:
                    result = active_install.to_dict()
                    self.logger.info(f"Found active install: ID {active_install.id}")
                    return result
                else:
                    self.logger.info("No active install found")
                    return None
                    
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting active install: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error getting active install: {e}")
            return None
    
    def get_current_state(self) -> Dict[str, Any]:
        """
        Get current state information.
        
        Returns:
            Dictionary containing current state information
        """
        return {
            "connected": self.connected,
            "state": self.state,
            "table_prefix": self.table_prefix,
            "current_install": self.current_install,
            "current_spaces": self.current_spaces,
            "current_users": self.current_users
        }
    
    # Space management methods
    async def list_spaces(self) -> List[Dict[str, Any]]:
        """
        List all graph spaces.
        
        Returns:
            List of space dictionaries
        """
        try:
            self.logger.info("Listing all spaces")
            
            if not self.connected or not self.session_factory:
                self.logger.error("Not connected to database")
                return []
            
            with self.session_factory() as session:
                spaces = session.query(self.Space).all()
                result = [space.to_dict() for space in spaces]
                
                self.logger.info(f"Found {len(result)} spaces")
                return result
                
        except SQLAlchemyError as e:
            self.logger.error(f"Database error listing spaces: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Unexpected error listing spaces: {e}")
            return []
    
    async def get_space_by_id(self, space_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a space by its ID.
        
        Args:
            space_id: Space identifier
            
        Returns:
            Space dictionary or None if not found
        """
        try:
            self.logger.info(f"Getting space by ID: {space_id}")
            
            if not self.connected or not self.session_factory:
                self.logger.error("Not connected to database")
                return None
            
            with self.session_factory() as session:
                space = session.query(self.Space).filter(self.Space.id == int(space_id)).first()
                
                if space:
                    result = space.to_dict()
                    self.logger.info(f"Found space: {result['space']}")
                    return result
                else:
                    self.logger.info(f"Space with ID {space_id} not found")
                    return None
                    
        except ValueError as e:
            self.logger.error(f"Invalid space ID: {space_id}")
            return None
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting space: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error getting space: {e}")
            return None
    
    async def filter_spaces_by_name(self, name_filter: str) -> List[Dict[str, Any]]:
        """
        Filter spaces by name (case-insensitive partial match).
        
        Args:
            name_filter: String to filter space names
            
        Returns:
            List of matching space dictionaries
        """
        try:
            self.logger.info(f"Filtering spaces by name: '{name_filter}'")
            
            if not self.connected or not self.session_factory:
                self.logger.error("Not connected to database")
                return []
            
            with self.session_factory() as session:
                # Filter by name (case-insensitive partial match on space_name)
                query = session.query(self.Space).filter(self.Space.space_name.ilike(f"%{name_filter}%"))
                spaces = query.all()
                result = [space.to_dict() for space in spaces]
                
                self.logger.info(f"Found {len(result)} spaces matching '{name_filter}'")
                return result
                
        except SQLAlchemyError as e:
            self.logger.error(f"Database error filtering spaces: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Unexpected error filtering spaces: {e}")
            return []
    
    async def add_space(self, space_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Add a new space.
        
        Args:
            space_data: Space configuration data containing tenant, space, space_name, space_description
            
        Returns:
            Created space data dictionary if successful, None otherwise
        """
        try:
            space_id = space_data.get('space', 'unknown')
            self.logger.info(f"Adding space: {space_id}")
            
            if not self.connected or not self.session_factory:
                self.logger.error("Not connected to database")
                return None
            
            # Validate required fields (space and space_name required, tenant optional)
            required_fields = ['space', 'space_name']
            for field in required_fields:
                if field not in space_data or not space_data[field]:
                    self.logger.error(f"Missing required field: {field}")
                    return None
            
            with self.session_factory() as session:
                # Pre-validation: Check space_id uniqueness
                existing_space = session.query(self.Space).filter(
                    self.Space.space == space_data['space']
                ).first()
                
                if existing_space:
                    self.logger.warning(f"Space identifier {space_id} already exists")
                    raise ValueError(f"Space identifier '{space_data['space']}' already exists. Please choose a different space identifier.")
                
                # Create new Space instance
                new_space = self.Space(
                    tenant=space_data['tenant'],
                    space=space_data['space'],
                    space_name=space_data.get('space_name'),
                    space_description=space_data.get('space_description')
                )
                
                session.add(new_space)
                try:
                    session.commit()
                except IntegrityError as e:
                    session.rollback()
                    self.logger.error(f"Integrity constraint violation adding space: {e}")
                    # Check if it's a uniqueness constraint violation
                    error_msg = str(e.orig).lower() if hasattr(e, 'orig') else str(e).lower()
                    if 'unique' in error_msg and 'space' in error_msg:
                        raise ValueError(f"Space identifier '{space_data.get('space', '')}' already exists. Please choose a different space identifier.")
                    else:
                        raise ValueError(f"Database constraint violation: {str(e)}")
                else:
                    # Refresh to get the ID and update_time from database
                    session.refresh(new_space)
                    
                    result = new_space.to_dict()
                    self.logger.info(f"Space added successfully: {result}")
                    return result
                
        except ValueError as e:
            self.logger.error(f"Validation error adding space: {str(e)}")
            raise  # Re-raise ValueError for API layer to handle
        except SQLAlchemyError as e:
            self.logger.error(f"Database error adding space: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error adding space: {e}")
            return None
    
    async def update_space(self, space_id: str, space_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Update an existing space.
        
        Args:
            space_id: Space identifier
            space_data: Updated space data
            
        Returns:
            Updated space data dictionary if successful, None otherwise
        """
        try:
            new_space_id = space_data.get('space', 'unknown')
            self.logger.info(f"Updating space {space_id}: {new_space_id}")
            
            if not self.connected or not self.session_factory:
                self.logger.error("Not connected to database")
                return None
            
            with self.session_factory() as session:
                space = session.query(self.Space).filter(self.Space.id == int(space_id)).first()
                
                if not space:
                    self.logger.warning(f"Space with ID {space_id} not found")
                    return None
                
                # Pre-validation: Check space_id uniqueness (excluding current space)
                if 'space' in space_data:
                    existing_space = session.query(self.Space).filter(
                        self.Space.space == space_data['space'],
                        self.Space.id != int(space_id)  # Exclude current space
                    ).first()
                    
                    if existing_space:
                        self.logger.warning(f"Space identifier {space_data['space']} already exists (excluding current space)")
                        raise ValueError(f"Space identifier '{space_data['space']}' already exists. Please choose a different space identifier.")
                
                # Update fields if provided (ignore id - server controlled)
                if 'tenant' in space_data:
                    space.tenant = space_data['tenant']
                if 'space' in space_data:
                    space.space = space_data['space']
                if 'space_name' in space_data:
                    space.space_name = space_data['space_name']
                if 'space_description' in space_data:
                    space.space_description = space_data['space_description']
                # Note: id and update_time are ignored - server controlled
                
                try:
                    session.commit()
                    # Refresh to get the updated data including new update_time
                    session.refresh(space)
                    result = space.to_dict()
                    self.logger.info(f"Space {space_id} updated successfully: {result}")
                    return result
                except IntegrityError as e:
                    session.rollback()
                    self.logger.error(f"Integrity constraint violation updating space: {e}")
                    # Check if it's a uniqueness constraint violation
                    error_msg = str(e.orig).lower() if hasattr(e, 'orig') else str(e).lower()
                    if 'unique' in error_msg and 'space' in error_msg:
                        raise ValueError(f"Space identifier '{space_data.get('space', '')}' already exists. Please choose a different space identifier.")
                    else:
                        raise ValueError(f"Database constraint violation: {str(e)}")
        
        except ValueError as e:
            self.logger.error(f"Validation error updating space: {str(e)}")
            raise  # Re-raise ValueError for API layer to handle
        except SQLAlchemyError as e:
            self.logger.error(f"Database error updating space: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error updating space: {e}")
            return None
    
    async def remove_space(self, space_id: str) -> bool:
        """
        Remove a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            True if space removed successfully, False otherwise
        """
        try:
            self.logger.info(f"Removing space: {space_id}")
            
            if not self.connected or not self.session_factory:
                self.logger.error("Not connected to database")
                return False
            
            with self.session_factory() as session:
                space = session.query(self.Space).filter(self.Space.id == int(space_id)).first()
                
                if not space:
                    self.logger.warning(f"Space with ID {space_id} not found")
                    return False
                
                session.delete(space)
                session.commit()
                
                self.logger.info(f"Space {space_id} removed successfully")
                return True
                
        except ValueError as e:
            self.logger.error(f"Invalid space ID: {space_id}")
            return False
        except SQLAlchemyError as e:
            self.logger.error(f"Database error removing space: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error removing space: {e}")
            return False
    
    # User management methods
    async def list_users(self) -> List[Dict[str, Any]]:
        """
        List all database users.
        
        Returns:
            List of user dictionaries (without passwords)
        """
        try:
            self.logger.info("Listing all users")
            
            if not self.connected or not self.session_factory:
                self.logger.error("Not connected to database")
                return []
            
            with self.session_factory() as session:
                users = session.query(self.User).all()
                result = [user.to_dict() for user in users]
                
                self.logger.info(f"Found {len(result)} users")
                return result
                
        except SQLAlchemyError as e:
            self.logger.error(f"Database error listing users: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Unexpected error listing users: {e}")
            return []
    
    async def add_user(self, user_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Add a new user.
        
        Args:
            user_data: User configuration data containing tenant, username, password, email
            
        Returns:
            Created user data dictionary if successful, None otherwise
        """
        try:
            username = user_data.get('username', 'unknown')
            email = user_data.get('email')
            self.logger.info(f"Adding user: {username}")
            
            if not self.connected or not self.session_factory:
                self.logger.error("Not connected to database")
                return None
            
            # Validate required fields
            required_fields = ['tenant', 'username', 'password']
            for field in required_fields:
                if field not in user_data:
                    self.logger.error(f"Missing required field: {field}")
                    return None
            
            with self.session_factory() as session:
                # Pre-validation: Check username uniqueness (global, not tenant-scoped)
                existing_username = session.query(self.User).filter(
                    self.User.username == user_data['username']
                ).first()
                
                if existing_username:
                    self.logger.warning(f"Username {username} already exists globally")
                    raise ValueError(f"Username '{user_data.get('username', '')}' already exists. Please choose a different username.")
                
                # Pre-validation: Check email uniqueness (global, not tenant-scoped, if email provided)
                if email:
                    existing_email = session.query(self.User).filter(
                        self.User.email == email
                    ).first()
                    
                    if existing_email:
                        self.logger.warning(f"Email {email} already exists globally")
                        raise ValueError(f"Email address '{email}' already exists. Please use a different email address.")
                
                # Create new User instance
                # Note: In production, password should be hashed before storing
                new_user = self.User(
                    tenant=user_data['tenant'],
                    username=user_data['username'],
                    password=user_data['password'],  # TODO: Hash password
                    email=email
                )
                
                session.add(new_user)
                try:
                    session.commit()
                except IntegrityError as e:
                    session.rollback()
                    self.logger.error(f"Integrity constraint violation adding user: {e}")
                    # Check if it's a uniqueness constraint violation
                    error_msg = str(e.orig).lower() if hasattr(e, 'orig') else str(e).lower()
                    if 'unique' in error_msg:
                        if 'username' in error_msg:
                            raise ValueError(f"Username '{user_data.get('username', '')}' already exists. Please choose a different username.")
                        elif 'email' in error_msg:
                            raise ValueError(f"Email address '{user_data.get('email', '')}' already exists. Please use a different email address.")
                        else:
                            raise ValueError(f"A user with this information already exists. Please check username and email address.")
                    else:
                        raise ValueError(f"Database constraint violation: {str(e)}")
                else:
                    # Refresh to get the ID and update_time from database
                    session.refresh(new_user)
                    
                    result = new_user.to_dict()
                    # Include password in response
                    
                    self.logger.info(f"User {username} added successfully with ID: {new_user.id}")
                    return result
        except ValueError as e:
            self.logger.error(f"Validation error adding user: {str(e)}")
            raise  # Re-raise ValueError for API layer to handle
        except SQLAlchemyError as e:
            self.logger.error(f"Database error adding user: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error adding user: {e}")
            return None
    
    async def update_user(self, user_id: str, user_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Update an existing user.
        
        Args:
            user_id: User identifier
            user_data: Updated user data
            
        Returns:
            Updated user data dictionary if successful, None otherwise
        """
        try:
            username = user_data.get('username', 'unknown')
            email = user_data.get('email')
            self.logger.info(f"Updating user {user_id}: {username}")
            
            if not self.connected or not self.session_factory:
                self.logger.error("Not connected to database")
                return None
            
            with self.session_factory() as session:
                user = session.query(self.User).filter(self.User.id == int(user_id)).first()
                
                if not user:
                    self.logger.warning(f"User with ID {user_id} not found")
                    return None
                
                # Pre-validation: Check username uniqueness globally (excluding current user)
                if 'username' in user_data:
                    existing_username = session.query(self.User).filter(
                        self.User.username == user_data['username'],
                        self.User.id != int(user_id)  # Exclude current user
                    ).first()
                    
                    if existing_username:
                        self.logger.warning(f"Username {user_data['username']} already exists globally (excluding current user)")
                        raise ValueError(f"Username '{user_data['username']}' already exists. Please choose a different username.")
                
                # Pre-validation: Check email uniqueness globally (excluding current user, if email provided)
                if 'email' in user_data and user_data['email']:
                    existing_email = session.query(self.User).filter(
                        self.User.email == user_data['email'],
                        self.User.id != int(user_id)  # Exclude current user
                    ).first()
                    
                    if existing_email:
                        self.logger.warning(f"Email {user_data['email']} already exists globally (excluding current user)")
                        raise ValueError(f"Email address '{user_data['email']}' already exists. Please use a different email address.")
                
                # Update fields if provided (ignore id - server controlled)
                if 'tenant' in user_data:
                    user.tenant = user_data['tenant']
                if 'username' in user_data:
                    user.username = user_data['username']
                if 'password' in user_data:
                    # TODO: Hash password before storing
                    user.password = user_data['password']
                if 'email' in user_data:
                    user.email = user_data['email']
                # Note: id and update_time are ignored - server controlled
                
                try:
                    session.commit()
                    # Refresh to get the updated data including new update_time
                    session.refresh(user)
                    result = user.to_dict()
                    self.logger.info(f"User {user_id} updated successfully: {result}")
                    return result
                except IntegrityError as e:
                    session.rollback()
                    self.logger.error(f"Integrity constraint violation updating user: {e}")
                    # Check if it's a uniqueness constraint violation
                    error_msg = str(e.orig).lower() if hasattr(e, 'orig') else str(e).lower()
                    if 'unique' in error_msg:
                        if 'username' in error_msg:
                            raise ValueError(f"Username '{user_data.get('username', '')}' already exists. Please choose a different username.")
                        elif 'email' in error_msg:
                            raise ValueError(f"Email address '{user_data.get('email', '')}' already exists. Please use a different email address.")
                        else:
                            raise ValueError(f"A user with this information already exists. Please check username and email address.")
                    else:
                        raise ValueError(f"Database constraint violation: {str(e)}")
            
        except ValueError as e:
            self.logger.error(f"Validation error updating user: {str(e)}")
            raise  # Re-raise ValueError for API layer to handle
        except SQLAlchemyError as e:
            self.logger.error(f"Database error updating user: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error updating user: {e}")
            return None
    
    async def remove_user(self, user_id: str) -> bool:
        """
        Remove a user.
        
        Args:
            user_id: User identifier
            
        Returns:
            True if user removed successfully, False otherwise
        """
        try:
            self.logger.info(f"Removing user: {user_id}")
            
            if not self.connected or not self.session_factory:
                self.logger.error("Not connected to database")
                return False
            
            with self.session_factory() as session:
                user = session.query(self.User).filter(self.User.id == int(user_id)).first()
                
                if not user:
                    self.logger.warning(f"User with ID {user_id} not found")
                    return False
                
                username = user.username
                session.delete(user)
                session.commit()
                
                self.logger.info(f"User {username} (ID: {user_id}) removed successfully")
                return True
                
        except ValueError as e:
            self.logger.error(f"Invalid user ID: {user_id}")
            return False
        except SQLAlchemyError as e:
            self.logger.error(f"Database error removing user: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error removing user: {e}")
            return False
    
    async def get_user_by_id(self, user_id: str) -> Dict[str, Any]:
        """
        Get a user by ID.
        
        Args:
            user_id: User identifier
            
        Returns:
            User dictionary (without password) if found, None otherwise
        """
        try:
            self.logger.info(f"Getting user by ID: {user_id}")
            
            if not self.connected or not self.session_factory:
                self.logger.error("Not connected to database")
                return None
            
            with self.session_factory() as session:
                user = session.query(self.User).filter(self.User.id == int(user_id)).first()
                
                if user:
                    result = user.to_dict()
                    self.logger.info(f"Found user: {result['username']}")
                    return result
                else:
                    self.logger.info(f"User with ID {user_id} not found")
                    return None
                    
        except ValueError as e:
            self.logger.error(f"Invalid user ID: {user_id}")
            return None
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting user by ID: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error getting user by ID: {e}")
            return None
    
    async def filter_users_by_name(self, name_filter: str) -> List[Dict[str, Any]]:
        """
        Filter users by name (case-insensitive partial match).
        
        Args:
            name_filter: String to search for in user names
            
        Returns:
            List of user dictionaries (without passwords) matching the filter
        """
        try:
            self.logger.info(f"Filtering users by name: '{name_filter}'")
            
            if not self.connected or not self.session_factory:
                self.logger.error("Not connected to database")
                return []
            
            with self.session_factory() as session:
                # Case-insensitive partial match on username
                query = session.query(self.User).filter(
                    self.User.username.ilike(f"%{name_filter}%")
                )
                
                users = query.all()
                result = [user.to_dict() for user in users]
                
                self.logger.info(f"Found {len(result)} users matching '{name_filter}'")
                return result
                
        except SQLAlchemyError as e:
            self.logger.error(f"Database error filtering users by name: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Unexpected error filtering users by name: {e}")
            return []
    
    # Database maintenance methods
    async def rebuild_indexes(self) -> bool:
        """
        Rebuild all database indexes.
        
        Returns:
            True if rebuild successful, False otherwise
        """
        self.logger.info("Rebuilding database indexes...")
        # TODO: Implement index rebuilding logic
        return True
    
    async def rebuild_stats(self) -> bool:
        """
        Rebuild database statistics for performance.
        
        Returns:
            True if rebuild successful, False otherwise
        """
        self.logger.info("Rebuilding database statistics...")
        # TODO: Implement statistics rebuilding logic
        return True
    
    async def list_tables(self) -> List[str]:
        """
        List all tables in the database.
        
        Returns:
            List of table names
        """
        self.logger.info("Listing database tables...")
        
        if not self.connected:
            self.logger.warning("Cannot list tables: not connected to database")
            return []
        
        try:
            # Query PostgreSQL information_schema to get all table names
            query = text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                ORDER BY table_name
            """)
            
            with self.engine.connect() as conn:
                result = conn.execute(query)
                tables = [row[0] for row in result.fetchall()]
                
            self.logger.info(f"Found {len(tables)} tables in database")
            return tables
            
        except Exception as e:
            self.logger.error(f"Error listing tables: {e}")
            return []
    
    async def list_indexes(self) -> List[Dict[str, Any]]:
        """
        List database indexes.
        
        Returns:
            List of index information dictionaries
        """
        self.logger.info("Listing database indexes...")
        # TODO: Implement index listing logic
        return []
    
    # Utility methods
    def is_connected(self) -> bool:
        """
        Check if database is connected.
        
        Returns:
            True if connected, False otherwise
        """
        return self.connected
    
    def get_session(self):
        """
        Get a database session.
        
        Returns:
            SQLAlchemy session instance
            
        Raises:
            RuntimeError: If not connected to database
        """
        if not self.connected or not self.session_factory:
            raise RuntimeError("Not connected to database")
        
        return self.session_factory()
