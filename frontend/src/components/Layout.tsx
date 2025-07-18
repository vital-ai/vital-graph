import React, { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { 
  Button,
  DarkThemeToggle,
  Navbar,
  NavbarBrand, 
  NavbarCollapse, 
  NavbarLink, 
  NavbarToggle,
  Sidebar,
  SidebarItem,
  SidebarItems,
  SidebarItemGroup
} from 'flowbite-react';
import { 
  HiChartPie, 
  HiInbox, 
  HiShoppingBag, 
  HiUser, 
  HiViewBoards,
  HiLogout
} from 'react-icons/hi';
import { useAuth } from '../contexts/AuthContext';

const Layout: React.FC = () => {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const { user, logout } = useAuth();
  
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
        <NavbarBrand href="/">
          <img src="/flowbite-react.svg" className="mr-3 h-6 sm:h-9" alt="Flowbite Logo" />
          <span className="self-center whitespace-nowrap text-xl font-semibold dark:text-white">VitalGraph</span>
        </NavbarBrand>
        <div className="flex md:order-2 items-center">
          {user && (
            <div className="mr-4 flex items-center">
              {user.profile_image ? (
                <img 
                  src={user.profile_image}
                  alt={user.full_name}
                  className="w-8 h-8 rounded-full mr-2 object-cover border border-gray-200 dark:border-gray-600"
                  onError={(e) => {
                    // If image fails to load, replace with initial avatar
                    const imgElement = e.currentTarget as HTMLImageElement;
                    imgElement.style.display = 'none';
                    
                    // Find the fallback avatar element and show it
                    const fallbackAvatar = document.querySelector('.fallback-avatar');
                    if (fallbackAvatar instanceof HTMLElement) {
                      fallbackAvatar.style.display = 'flex';
                    }
                  }}
                />
              ) : null}
              <div 
                className={`w-8 h-8 rounded-full mr-2 bg-blue-600 flex items-center justify-center text-white font-medium fallback-avatar ${user.profile_image ? 'hidden' : ''}`}
                title={user.full_name}
              >
                {user.full_name?.charAt(0).toUpperCase() || 'U'}
              </div>
              <span className="hidden md:inline text-sm font-medium dark:text-white">
                {user.full_name}
              </span>
            </div>
          )}
          <DarkThemeToggle className="mr-2" />
          <Button color="failure" onClick={handleLogout} size="sm">
            <HiLogout className="mr-2 h-5 w-5" />
            <span className="hidden sm:inline">Logout</span>
          </Button>
          <NavbarToggle className="ml-2" />
        </div>
        <NavbarCollapse>
          <NavbarLink href="/" active>
            Home
          </NavbarLink>
          <NavbarLink href="/spaces">Spaces</NavbarLink>
          <NavbarLink href="/sparql">SPARQL</NavbarLink>
        </NavbarCollapse>
      </Navbar>

      <div className="flex flex-1">
        {/* Sidebar */}
        <Sidebar aria-label="Application sidebar" collapsed={!isSidebarOpen} className="w-fit">
          <SidebarItems>
            <SidebarItemGroup>
              <SidebarItem href="/" icon={HiChartPie}>
                Home
              </SidebarItem>
              <SidebarItem href="/spaces" icon={HiViewBoards} label="Pro" labelColor="dark">
                Spaces
              </SidebarItem>
              <SidebarItem href="/sparql" icon={HiInbox} label="3">
                SPARQL
              </SidebarItem>
              <SidebarItem href="/users" icon={HiUser}>
                Users
              </SidebarItem>
              <SidebarItem href="/products" icon={HiShoppingBag}>
                Products
              </SidebarItem>
            </SidebarItemGroup>
          </SidebarItems>
        </Sidebar>

        {/* Content area */}
        <main className="flex-1 p-4">
          <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-800 sm:p-6 lg:p-8">
            {/* Outlet for nested routes */}
            <Outlet />
            
            <Button onClick={toggleSidebar} className="mt-4">
              Toggle Sidebar
            </Button>
          </div>
        </main>
      </div>
    </div>
  );
};

export default Layout;
