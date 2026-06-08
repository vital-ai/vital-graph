import React, { useState, lazy, Suspense } from 'react';
import { Outlet, useLocation, useNavigate, Link } from 'react-router-dom';
import { 
  Avatar,
  Badge,
  DarkThemeToggle,
  Dropdown,
  DropdownHeader,
  DropdownItem,
  Navbar,
  Sidebar,
  SidebarCollapse,
  SidebarItem,
  SidebarItems,
  SidebarItemGroup,
} from 'flowbite-react';
import { 
  HiHome, 
  HiViewBoards,
  HiLogout,
  HiKey,
  HiMenu,
  HiCube,
  HiCog,
  HiDatabase,
  HiSearch,
} from 'react-icons/hi';
import { useAuth } from '../contexts/AuthContext';
import GraphIcon from './icons/GraphIcon';
import DataIcon from './icons/DataIcon';
import CommandPalette from './CommandPalette';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';

const PasswordChangeDialog = lazy(() => import('./PasswordChangeDialog'));

const Layout: React.FC = () => {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [showPasswordDialog, setShowPasswordDialog] = useState(false);
  const [showCommandPalette, setShowCommandPalette] = useState(false);
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  
  const toggleSidebar = () => {
    setIsSidebarOpen(!isSidebarOpen);
  };

  // Auto-close sidebar on mobile when route changes
  React.useEffect(() => {
    setIsSidebarOpen(false);
  }, [location.pathname]);

  // Global keyboard shortcuts
  useKeyboardShortcuts([
    { key: 'k', ctrl: true, handler: () => setShowCommandPalette(true) },
    { key: 'Escape', handler: () => setShowCommandPalette(false) },
  ]);

  const handleLogout = () => {
    logout();
  };

  return (
    <div className="flex flex-col min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Navbar */}
      <Navbar fluid rounded className="border-b border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
        <div className="flex items-center">
          {/* Mobile sidebar toggle */}
          <button
            onClick={toggleSidebar}
            aria-label="Toggle sidebar menu"
            className="mr-3 rounded-lg p-2 text-gray-600 hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-gray-200 dark:text-gray-400 dark:hover:bg-gray-700 dark:focus:ring-gray-600 md:hidden"
          >
            <HiMenu className="h-6 w-6" />
          </button>
          <Link to="/">
            <span className="flex items-center">
              <img 
                src="/images/vital-logo-black.png" 
                className="mr-3 h-6 sm:h-9 w-auto block dark:hidden" 
                alt="VitalGraph Logo" 
                style={{ maxWidth: '120px' }}
              />
              <img 
                src="/images/vitallogo_offwhite_normal.png" 
                className="mr-3 h-6 sm:h-9 w-auto hidden dark:block" 
                alt="VitalGraph Logo" 
                style={{ maxWidth: '120px' }}
              />
              <span className="self-center whitespace-nowrap text-xl font-semibold dark:text-white">VitalGraph</span>
            </span>
          </Link>
        </div>
        <div className="flex md:order-2 items-center">
          {/* Command palette trigger */}
          <button
            onClick={() => setShowCommandPalette(true)}
            aria-label="Open command palette (Ctrl+K)"
            className="hidden sm:flex items-center gap-2 mr-3 px-3 py-1.5 text-sm text-gray-400 bg-gray-100 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-lg hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
          >
            <HiSearch className="w-4 h-4" />
            <span className="text-xs">Search...</span>
            <kbd className="ml-2 px-1.5 py-0.5 text-[10px] font-mono bg-white dark:bg-gray-600 border border-gray-300 dark:border-gray-500 rounded">⌘K</kbd>
          </button>
          <DarkThemeToggle className="mr-2" />
          {user && (
            <Dropdown
              arrowIcon={false}
              inline
              label={
                <Avatar
                  alt="User"
                  img="/images/generic-user-avatar.svg"
                  rounded
                  size="sm"
                />
              }
            >
              <DropdownHeader>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{user.full_name}</span>
                  <Badge color={user.role === 'admin' ? 'purple' : user.role === 'user' ? 'blue' : 'gray'} size="xs">
                    {user.role}
                  </Badge>
                </div>
                <span className="block truncate text-sm text-gray-500">{user.email}</span>
              </DropdownHeader>
              <DropdownItem icon={HiKey} onClick={() => setShowPasswordDialog(true)}>
                Change Password
              </DropdownItem>
              <DropdownItem icon={HiKey} onClick={() => navigate('/api-keys')}>
                API Keys
              </DropdownItem>
              <DropdownItem icon={HiLogout} onClick={handleLogout}>
                Sign out
              </DropdownItem>
            </Dropdown>
          )}
        </div>
      </Navbar>

      <div className="flex flex-1 relative">
        {/* Mobile overlay */}
        {isSidebarOpen && (
          <div 
            className="fixed inset-0 z-40 bg-black bg-opacity-50 md:hidden" 
            onClick={() => setIsSidebarOpen(false)}
            aria-hidden="true"
          />
        )}
        
        {/* Sidebar */}
        <Sidebar 
          aria-label="Application sidebar" 
          className={`
            w-fit transition-transform duration-300 ease-in-out z-50
            md:translate-x-0 md:static md:block
            ${isSidebarOpen ? 'translate-x-0' : '-translate-x-full'}
            fixed top-[64px] md:top-auto md:relative h-[calc(100vh-64px)] md:h-full overflow-y-auto
          `}
        >
          <SidebarItems>
            {/* Core Navigation */}
            <SidebarItemGroup>
              <Link to="/" style={{display: 'block'}}>
                <SidebarItem icon={HiHome} active={location.pathname === '/'} as="div">
                  Home
                </SidebarItem>
              </Link>
              <Link to="/spaces" style={{display: 'block'}}>
                <SidebarItem icon={HiViewBoards} active={location.pathname === '/spaces'} as="div">
                  Spaces
                </SidebarItem>
              </Link>
              <Link to="/graphs" style={{display: 'block'}}>
                <SidebarItem icon={GraphIcon} active={location.pathname === '/graphs'} as="div">
                  Graphs
                </SidebarItem>
              </Link>
            </SidebarItemGroup>

            {/* Knowledge Graph */}
            <SidebarItemGroup>
              <SidebarCollapse icon={HiDatabase} label="Knowledge Graph" open={location.pathname.startsWith('/objects') || location.pathname.includes('/kg-types') || location.pathname.includes('/kg-query-builder') || location.pathname.includes('/triples') || location.pathname.includes('/files') || location.pathname.includes('/sparql')}>
                <Link to="/objects" style={{display: 'block'}}>
                  <SidebarItem active={location.pathname.startsWith('/objects') || location.pathname.includes('/objects')} as="div">
                    Objects
                  </SidebarItem>
                </Link>
                <Link to="/kg-types" style={{display: 'block'}}>
                  <SidebarItem active={location.pathname === '/kg-types'} as="div">
                    KG Types
                  </SidebarItem>
                </Link>
                <Link to="/triples" style={{display: 'block'}}>
                  <SidebarItem active={location.pathname === '/triples'} as="div">
                    Triples
                  </SidebarItem>
                </Link>
                <Link to="/files" style={{display: 'block'}}>
                  <SidebarItem active={location.pathname === '/files'} as="div">
                    Files
                  </SidebarItem>
                </Link>
                <Link to="/kg-query-builder" style={{display: 'block'}}>
                  <SidebarItem active={location.pathname === '/kg-query-builder'} as="div">
                    Query Builder
                  </SidebarItem>
                </Link>
                <Link to="/sparql" style={{display: 'block'}}>
                  <SidebarItem active={location.pathname === '/sparql'} as="div">
                    SPARQL
                  </SidebarItem>
                </Link>
              </SidebarCollapse>
            </SidebarItemGroup>

            {/* Data */}
            <SidebarItemGroup>
              <Link to="/data" style={{display: 'block'}}>
                <SidebarItem icon={DataIcon} active={location.pathname.startsWith('/data')} as="div">
                  Data
                </SidebarItem>
              </Link>
            </SidebarItemGroup>

            {/* Vector & Geo */}
            <SidebarItemGroup>
              <SidebarCollapse icon={HiCube} label="Vector & Geo" open={location.pathname.includes('/vector') || location.pathname.includes('/geo')}>
                <Link to="/vector-indexes" style={{display: 'block'}}>
                  <SidebarItem active={location.pathname === '/vector-indexes'} as="div">
                    Indexes
                  </SidebarItem>
                </Link>
                <Link to="/vector-mappings" style={{display: 'block'}}>
                  <SidebarItem active={location.pathname === '/vector-mappings'} as="div">
                    Mappings
                  </SidebarItem>
                </Link>
                <Link to="/vector-search" style={{display: 'block'}}>
                  <SidebarItem active={location.pathname === '/vector-search'} as="div">
                    Search
                  </SidebarItem>
                </Link>
                <Link to="/geo-points" style={{display: 'block'}}>
                  <SidebarItem active={location.pathname === '/geo-points'} as="div">
                    Geo Points
                  </SidebarItem>
                </Link>
              </SidebarCollapse>
            </SidebarItemGroup>

            {/* Administration (admin only) */}
            {user?.role === 'admin' && (
              <SidebarItemGroup>
                <SidebarCollapse icon={HiCog} label="Administration" open={location.pathname.startsWith('/users') || location.pathname.startsWith('/api-keys') || location.pathname.startsWith('/admin') || location.pathname.startsWith('/audit-log') || location.pathname.startsWith('/entity-registry') || location.pathname.startsWith('/agent-registry')}>
                  <Link to="/users" style={{display: 'block'}}>
                    <SidebarItem active={location.pathname === '/users'} as="div">
                      Users
                    </SidebarItem>
                  </Link>
                  <Link to="/api-keys" style={{display: 'block'}}>
                    <SidebarItem active={location.pathname === '/api-keys'} as="div">
                      API Keys
                    </SidebarItem>
                  </Link>
                  <Link to="/audit-log" style={{display: 'block'}}>
                    <SidebarItem active={location.pathname === '/audit-log'} as="div">
                      Audit Log
                    </SidebarItem>
                  </Link>
                  <Link to="/entity-registry" style={{display: 'block'}}>
                    <SidebarItem active={location.pathname.startsWith('/entity-registry')} as="div">
                      Entity Registry
                    </SidebarItem>
                  </Link>
                  <Link to="/agent-registry" style={{display: 'block'}}>
                    <SidebarItem active={location.pathname.startsWith('/agent-registry')} as="div">
                      Agent Registry
                    </SidebarItem>
                  </Link>
                  <Link to="/admin" style={{display: 'block'}}>
                    <SidebarItem active={location.pathname === '/admin'} as="div">
                      System
                    </SidebarItem>
                  </Link>
                </SidebarCollapse>
              </SidebarItemGroup>
            )}
          </SidebarItems>
        </Sidebar>

        {/* Content area */}
        <main className="flex-1 p-4 overflow-auto">
          <Outlet />
        </main>
      </div>

      {/* Password Change Dialog */}
      <Suspense fallback={null}>
        <PasswordChangeDialog show={showPasswordDialog} onClose={() => setShowPasswordDialog(false)} />
      </Suspense>

      {/* Command Palette (Ctrl+K) */}
      <CommandPalette isOpen={showCommandPalette} onClose={() => setShowCommandPalette(false)} />
    </div>
  );
};

export default Layout;
