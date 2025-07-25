from vitalgraph.config.config_loader import get_config, ConfigurationError
from vitalgraph.db.postgresql.postgresql_db_impl import PostgreSQLDbImpl
from vitalgraph.space.space_manager import SpaceManager


class VitalGraphImpl:
    def __init__(self, config=None):
        self.config = config
        
        # Load VitalGraph configuration if not provided
        if self.config is None:
            try:
                self.config = get_config()
            except ConfigurationError as e:
                print(f"Warning: Could not load VitalGraph configuration: {e}")
                self.config = None
        
        # Initialize database implementation
        self.db_impl = None
        if self.config:
            try:
                db_config = self.config.get_database_config()
                tables_config = self.config.get_tables_config()
                self.db_impl = PostgreSQLDbImpl(db_config, tables_config, config_loader=self.config)
                print(f"✅ Initialized database implementation successfully with RDF connection pool support")
            except Exception as e:
                print(f"Warning: Could not initialize database: {e}")
                self.db_impl = None
        
        # Initialize SpaceManager with database implementation
        self.space_manager = SpaceManager(db_impl=self.db_impl)
        print(f"✅ Initialized SpaceManager successfully")
    
    def get_db_impl(self):
        """Return the PostgreSQL database implementation instance."""
        return self.db_impl
    
    def get_config(self):
        """Return the VitalGraph configuration instance."""
        return self.config
    
    def get_space_manager(self):
        """Return the SpaceManager instance."""
        return self.space_manager
