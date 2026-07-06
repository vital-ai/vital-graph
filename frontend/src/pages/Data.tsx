import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Card } from 'flowbite-react';
import DataIcon from '../components/icons/DataIcon';
import DataImportPage from './DataImport';
import DataExportPage from './DataExport';

const Data: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [activeTab, setActiveTab] = useState<'import' | 'export'>('import');

  useEffect(() => {
    if (location.pathname === '/data/export') {
      setActiveTab('export');
    } else {
      setActiveTab('import');
    }
  }, [location.pathname]);

  return (
    <div className="space-y-6" data-testid="data-page">
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <DataIcon className="w-6 h-6 text-blue-600" />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Data Management
          </h1>
        </div>
        <p className="text-gray-600 dark:text-gray-400">
          Manage data imports and exports for your RDF graphs
        </p>
      </div>

      <Card>
        <div className="border-b border-gray-200 dark:border-gray-700">
          <nav className="-mb-px flex space-x-8">
            <button
              onClick={() => navigate('/data/import')}
              className={`py-2 px-1 border-b-2 font-medium text-sm ${
                activeTab === 'import'
                  ? 'border-blue-500 text-blue-600 dark:text-blue-500'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
              }`}
            >
              Data Import
            </button>
            <button
              onClick={() => navigate('/data/export')}
              className={`py-2 px-1 border-b-2 font-medium text-sm ${
                activeTab === 'export'
                  ? 'border-blue-500 text-blue-600 dark:text-blue-500'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
              }`}
            >
              Data Export
            </button>
          </nav>
        </div>
        
        <div className="p-6">
          {activeTab === 'import' && <DataImportPage />}
          {activeTab === 'export' && <DataExportPage />}
        </div>
      </Card>
    </div>
  );
};

export default Data;
