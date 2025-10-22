import React, { useState } from 'react';
import { Outlet, useLocation, Link } from 'react-router-dom';
import { 
  Avatar,
  DarkThemeToggle,
  Dropdown,
  DropdownHeader,
  DropdownItem,
  Navbar,
  NavbarCollapse, 
  NavbarToggle,
  Sidebar,
  SidebarItem,
  SidebarItems,
  SidebarItemGroup,
} from 'flowbite-react';
import { 
  HiHome, 
  HiSearch, 
  HiUser, 
  HiViewBoards,
  HiLogout,
  HiMenu,
  HiDocumentDuplicate
} from 'react-icons/hi';
import { useAuth } from '../contexts/AuthContext';
import GraphIcon from './icons/GraphIcon';
import ObjectIcon from './icons/ObjectIcon';
import TriplesIcon from './icons/TriplesIcon';
import KGTypesIcon from './icons/KGTypesIcon';
import DataIcon from './icons/DataIcon';

const Layout: React.FC = () => {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const { user, logout } = useAuth();
  const location = useLocation();
  
  const toggleSidebar = () => {
    setIsSidebarOpen(!isSidebarOpen);
  };

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
                <span className="block text-sm font-medium">{user.full_name}</span>
                <span className="block truncate text-sm text-gray-500">{user.email}</span>
              </DropdownHeader>
              <DropdownItem icon={HiLogout} onClick={handleLogout}>
                Sign out
              </DropdownItem>
            </Dropdown>
          )}
          <NavbarToggle className="ml-2" />
        </div>
        <NavbarCollapse>
          <Link to="/" className="block py-2 pr-4 pl-3 md:p-0">
            <span className={`block py-2 pr-4 pl-3 md:p-0 ${location.pathname === '/' ? 'text-blue-700 dark:text-blue-500' : 'text-gray-700 dark:text-white'}`}>
              Home
            </span>
          </Link>
          <Link to="/spaces" className="block py-2 pr-4 pl-3 md:p-0">
            <span className={`block py-2 pr-4 pl-3 md:p-0 ${location.pathname === '/spaces' ? 'text-blue-700 dark:text-blue-500' : 'text-gray-700 dark:text-white'}`}>
              Spaces
            </span>
          </Link>
          <Link to="/graphs" className="block py-2 pr-4 pl-3 md:p-0">
            <span className={`block py-2 pr-4 pl-3 md:p-0 ${location.pathname === '/graphs' ? 'text-blue-700 dark:text-blue-500' : 'text-gray-700 dark:text-white'}`}>
              Graphs
            </span>
          </Link>
          <Link to="/kg-types" className="block py-2 pr-4 pl-3 md:p-0">
            <span className={`block py-2 pr-4 pl-3 md:p-0 ${location.pathname === '/kg-types' ? 'text-blue-700 dark:text-blue-500' : 'text-gray-700 dark:text-white'}`}>
              KG Types
            </span>
          </Link>
          <Link to="/objects" className="block py-2 pr-4 pl-3 md:p-0">
            <span className={`block py-2 pr-4 pl-3 md:p-0 ${location.pathname === '/objects' ? 'text-blue-700 dark:text-blue-500' : 'text-gray-700 dark:text-white'}`}>
              Objects
            </span>
          </Link>
          <Link to="/triples" className="block py-2 pr-4 pl-3 md:p-0">
            <span className={`block py-2 pr-4 pl-3 md:p-0 ${location.pathname === '/triples' ? 'text-blue-700 dark:text-blue-500' : 'text-gray-700 dark:text-white'}`}>
              Triples
            </span>
          </Link>
          <Link to="/files" className="block py-2 pr-4 pl-3 md:p-0">
            <span className={`block py-2 pr-4 pl-3 md:p-0 ${location.pathname === '/files' ? 'text-blue-700 dark:text-blue-500' : 'text-gray-700 dark:text-white'}`}>
              Files
            </span>
          </Link>
          <Link to="/users" className="block py-2 pr-4 pl-3 md:p-0">
            <span className={`block py-2 pr-4 pl-3 md:p-0 ${location.pathname === '/users' ? 'text-blue-700 dark:text-blue-500' : 'text-gray-700 dark:text-white'}`}>
              Users
            </span>
          </Link>
          <Link to="/data" className="block py-2 pr-4 pl-3 md:p-0">
            <span className={`block py-2 pr-4 pl-3 md:p-0 ${location.pathname === '/data' ? 'text-blue-700 dark:text-blue-500' : 'text-gray-700 dark:text-white'}`}>
              Data
            </span>
          </Link>
          <Link to="/sparql" className="block py-2 pr-4 pl-3 md:p-0">
            <span className={`block py-2 pr-4 pl-3 md:p-0 ${location.pathname === '/sparql' ? 'text-blue-700 dark:text-blue-500' : 'text-gray-700 dark:text-white'}`}>
              SPARQL
            </span>
          </Link>
        </NavbarCollapse>
      </Navbar>

      <div className="flex flex-1 relative">
        {/* Mobile overlay */}
        {isSidebarOpen && (
          <div 
            className="fixed inset-0 z-40 bg-black bg-opacity-50 md:hidden" 
            onClick={() => setIsSidebarOpen(false)}
          />
        )}
        
        {/* Sidebar */}
        <Sidebar 
          aria-label="Application sidebar" 
          className={`
            w-fit transition-transform duration-300 ease-in-out z-50
            md:translate-x-0 md:static md:block
            ${isSidebarOpen ? 'translate-x-0' : '-translate-x-full'}
            fixed md:relative h-full
          `}
        >
          <SidebarItems>
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
              <Link to="/kg-types" style={{display: 'block'}}>
                <SidebarItem icon={KGTypesIcon} active={location.pathname === '/kg-types'} as="div">
                  KG Types
                </SidebarItem>
              </Link>
              <Link to="/objects" style={{display: 'block'}}>
                <SidebarItem icon={ObjectIcon} active={location.pathname === '/objects'} as="div">
                  Objects
                </SidebarItem>
              </Link>
              <Link to="/triples" style={{display: 'block'}}>
                <SidebarItem icon={TriplesIcon} active={location.pathname === '/triples'} as="div">
                  Triples
                </SidebarItem>
              </Link>
              <Link to="/files" style={{display: 'block'}}>
                <SidebarItem icon={HiDocumentDuplicate} active={location.pathname === '/files'} as="div">
                  Files
                </SidebarItem>
              </Link>
              <Link to="/users" style={{display: 'block'}}>
                <SidebarItem icon={HiUser} active={location.pathname === '/users'} as="div">
                  Users
                </SidebarItem>
              </Link>
              <Link to="/data" style={{display: 'block'}}>
                <SidebarItem icon={DataIcon} active={location.pathname === '/data'} as="div">
                  Data
                </SidebarItem>
              </Link>
              <Link to="/sparql" style={{display: 'block'}}>
                <SidebarItem icon={HiSearch} active={location.pathname === '/sparql'} as="div">
                  SPARQL
                </SidebarItem>
              </Link>
            </SidebarItemGroup>
          </SidebarItems>
        </Sidebar>

        {/* Content area */}
        <main className="flex-1 p-4">
          <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-800 sm:p-6 lg:p-8">
            {/* Outlet for nested routes */}
            <Outlet />
            
            {/* Toggle Sidebar button removed - sidebar always visible */}
          </div>
        </main>
      </div>
    </div>
  );
};

export default Layout;
