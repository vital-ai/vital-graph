import React, { useState, useEffect } from 'react';
import { Alert, Card } from 'flowbite-react';
import { HiUsers, HiViewBoards, HiDocumentDuplicate, HiUpload, HiDownload, HiCollection, HiSwitchHorizontal, HiEye, HiClock } from 'react-icons/hi';
import { Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import GraphIcon from '../components/icons/GraphIcon';
import ObjectIcon from '../components/icons/ObjectIcon';
import TriplesIcon from '../components/icons/TriplesIcon';
import FrameIcon from '../components/icons/FrameIcon';
import KGTypesIcon from '../components/icons/KGTypesIcon';
import DataIcon from '../components/icons/DataIcon';

const Home: React.FC = () => {
  const { user, showLoginSuccess, setShowLoginSuccess } = useAuth();
  const [showWelcome, setShowWelcome] = useState(false);
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    if (showLoginSuccess) {
      setShowWelcome(true);
      // Trigger fade in after a brief delay
      setTimeout(() => setIsVisible(true), 100);
      
      // Start fade out after 2.5 seconds, then hide after fade completes
      const fadeTimer = setTimeout(() => {
        setIsVisible(false);
      }, 2500);
      
      const hideTimer = setTimeout(() => {
        setShowWelcome(false);
        setShowLoginSuccess(false);
      }, 3000);
      
      return () => {
        clearTimeout(fadeTimer);
        clearTimeout(hideTimer);
      };
    }
  }, [showLoginSuccess, setShowLoginSuccess]);

  return (
    <div>
      <h1 className="mb-4 text-xl font-bold text-gray-900 dark:text-white">Welcome to VitalGraph</h1>
      
      {showWelcome && (
        <Alert 
          color="info" 
          className={`mb-4 transition-opacity duration-500 ${
            isVisible ? 'opacity-100' : 'opacity-0'
          }`}
        >
          <div className="font-medium">
            Hello, {user?.full_name || 'Admin User'}!
          </div>
          <div>
            You are successfully logged in as {user?.role || 'Administrator'}.
          </div>
        </Alert>
      )}
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-8 items-start">
        {/* Spaces & Users Section */}
        <Card>
          <div className="flex items-center gap-3 mb-4">
            <HiViewBoards className="w-6 h-6 text-blue-600" />
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Spaces & Users</h2>
          </div>
          <div className="space-y-3">
            <Link to="/spaces" className="flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-700 p-2 rounded-lg transition-colors">
              <div className="flex items-center gap-2">
                <HiViewBoards className="w-4 h-4 text-gray-500" />
                <span className="text-gray-700 dark:text-gray-300">Spaces</span>
              </div>
              <span className="text-sm font-medium text-blue-600">Organize your data</span>
            </Link>
            <Link to="/users" className="flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-700 p-2 rounded-lg transition-colors">
              <div className="flex items-center gap-2">
                <HiUsers className="w-4 h-4 text-gray-500" />
                <span className="text-gray-700 dark:text-gray-300">User Management</span>
              </div>
              <span className="text-sm font-medium text-green-600">Control access</span>
            </Link>
          </div>
        </Card>

        {/* Graphs & Triples Section */}
        <Card>
          <div className="flex items-center gap-3 mb-4">
            <GraphIcon className="w-6 h-6 text-blue-600" />
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Graphs & Triples</h2>
          </div>
          <div className="space-y-3">
            <Link to="/graphs" className="flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-700 p-2 rounded-lg transition-colors">
              <div className="flex items-center gap-2">
                <GraphIcon className="w-4 h-4 text-gray-500" />
                <span className="text-gray-700 dark:text-gray-300">Knowledge Graphs</span>
              </div>
              <span className="text-sm font-medium text-purple-600">Semantic data</span>
            </Link>
            <Link to="/triples" className="flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-700 p-2 rounded-lg transition-colors">
              <div className="flex items-center gap-2">
                <TriplesIcon className="w-4 h-4 text-gray-500" />
                <span className="text-gray-700 dark:text-gray-300">RDF Triples</span>
              </div>
              <span className="text-sm font-medium text-indigo-600">Knowledge Assertions</span>
            </Link>
          </div>
        </Card>

        {/* Objects & Files Section */}
        <Card>
          <div className="flex items-center gap-3 mb-4">
            <ObjectIcon className="w-6 h-6 text-blue-600" />
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Knowledge Graph & Files</h2>
          </div>
          <div className="space-y-3">
            <Link to="/objects" className="flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-700 p-2 rounded-lg transition-colors">
              <div className="flex items-center gap-2">
                <ObjectIcon className="w-4 h-4 text-gray-500" />
                <span className="text-gray-700 dark:text-gray-300">Graph Objects</span>
              </div>
              <span className="text-sm font-medium text-orange-600">Graph Objects</span>
            </Link>
            <Link to="/objects/kgentities" className="flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-700 p-2 rounded-lg transition-colors">
              <div className="flex items-center gap-2">
                <HiCollection className="w-4 h-4 text-gray-500" />
                <span className="text-gray-700 dark:text-gray-300">KG Entities</span>
              </div>
              <span className="text-sm font-medium text-blue-600">KG Entities</span>
            </Link>
            <Link to="/objects/kgframes" className="flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-700 p-2 rounded-lg transition-colors">
              <div className="flex items-center gap-2">
                <FrameIcon className="w-4 h-4 text-gray-500" />
                <span className="text-gray-700 dark:text-gray-300">KG Frames</span>
              </div>
              <span className="text-sm font-medium text-purple-600">KG Frames</span>
            </Link>
            <Link to="/kg-types" className="flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-700 p-2 rounded-lg transition-colors">
              <div className="flex items-center gap-2">
                <KGTypesIcon className="w-4 h-4 text-gray-500" />
                <span className="text-gray-700 dark:text-gray-300">KG Types</span>
              </div>
              <span className="text-sm font-medium text-indigo-600">KG Types</span>
            </Link>
            <Link to="/files" className="flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-700 p-2 rounded-lg transition-colors">
              <div className="flex items-center gap-2">
                <HiDocumentDuplicate className="w-4 h-4 text-gray-500" />
                <span className="text-gray-700 dark:text-gray-300">File Management</span>
              </div>
              <span className="text-sm font-medium text-teal-600">File Management</span>
            </Link>
          </div>
        </Card>

        {/* Data Management Section */}
        <Card>
          <div className="flex items-center gap-3 mb-4">
            <DataIcon className="w-6 h-6 text-blue-600" />
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Data Management</h2>
          </div>
          <div className="space-y-3">
            <Link to="/data/import" className="flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-700 p-2 rounded-lg transition-colors">
              <div className="flex items-center gap-2">
                <HiUpload className="w-4 h-4 text-gray-500" />
                <span className="text-gray-700 dark:text-gray-300">Data Import</span>
              </div>
              <span className="text-sm font-medium text-emerald-600">Ingest data</span>
            </Link>
            <Link to="/data/export" className="flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-700 p-2 rounded-lg transition-colors">
              <div className="flex items-center gap-2">
                <HiDownload className="w-4 h-4 text-gray-500" />
                <span className="text-gray-700 dark:text-gray-300">Data Export</span>
              </div>
              <span className="text-sm font-medium text-cyan-600">Export data</span>
            </Link>
            <Link to="/data/migrate" className="flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-700 p-2 rounded-lg transition-colors">
              <div className="flex items-center gap-2">
                <HiSwitchHorizontal className="w-4 h-4 text-gray-500" />
                <span className="text-gray-700 dark:text-gray-300">Data Migration</span>
              </div>
              <span className="text-sm font-medium text-orange-600">Migrate data</span>
            </Link>
            <Link to="/data/tracking" className="flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-700 p-2 rounded-lg transition-colors">
              <div className="flex items-center gap-2">
                <HiEye className="w-4 h-4 text-gray-500" />
                <span className="text-gray-700 dark:text-gray-300">Data Tracking</span>
              </div>
              <span className="text-sm font-medium text-purple-600">Data tracking</span>
            </Link>
            <Link to="/data/checkpoint" className="flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-700 p-2 rounded-lg transition-colors">
              <div className="flex items-center gap-2">
                <HiClock className="w-4 h-4 text-gray-500" />
                <span className="text-gray-700 dark:text-gray-300">Data Checkpoint</span>
              </div>
              <span className="text-sm font-medium text-indigo-600">Data checkpoint</span>
            </Link>
          </div>
        </Card>
      </div>

    </div>
  );
};

export default Home;
