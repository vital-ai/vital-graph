import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import {
  Card,
  Breadcrumb,
  BreadcrumbItem,
  Alert,
  Spinner
} from 'flowbite-react';
import {
  HiHome,
  HiChartBar
} from 'react-icons/hi';
import { mockSpaces, mockGraphs, type Space, type Graph } from '../mock';

// Mock data for graph type analysis
const mockGraphTypeData = [
  { type: 'Person', count: 1250, color: '#3B82F6' },
  { type: 'Organization', count: 890, color: '#10B981' },
  { type: 'Location', count: 650, color: '#F59E0B' },
  { type: 'Event', count: 420, color: '#EF4444' },
  { type: 'Document', count: 380, color: '#8B5CF6' },
  { type: 'Product', count: 290, color: '#06B6D4' },
  { type: 'Concept', count: 180, color: '#84CC16' },
  { type: 'Relationship', count: 120, color: '#F97316' }
];

const GraphAnalysis: React.FC = () => {
  const { spaceId, graphId } = useParams<{ spaceId: string; graphId: string }>();
  
  const [space, setSpace] = useState<Space | null>(null);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        // Simulate API call
        await new Promise(resolve => setTimeout(resolve, 300));
        
        const foundSpace = mockSpaces.find(s => s.space === spaceId);
        const foundGraph = mockGraphs.find(g => g.id === parseInt(graphId || '0'));
        
        if (!foundSpace || !foundGraph) {
          setError('Space or Graph not found');
          return;
        }
        
        setSpace(foundSpace);
        setGraph(foundGraph);
        setError(null);
      } catch (err) {
        console.error('Error fetching data:', err);
        setError('Failed to load analysis data. Please try again later.');
      } finally {
        setLoading(false);
      }
    };

    if (spaceId && graphId) {
      fetchData();
    }
  }, [spaceId, graphId]);

  const maxCount = Math.max(...mockGraphTypeData.map(item => item.count));

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <Spinner size="xl" />
      </div>
    );
  }

  if (error) {
    return (
      <Alert color="failure" className="mb-6">
        {error}
      </Alert>
    );
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <Breadcrumb aria-label="Graph analysis breadcrumb">
        <BreadcrumbItem href="/" icon={HiHome}>
          Home
        </BreadcrumbItem>
        <BreadcrumbItem href="/spaces">
          Spaces
        </BreadcrumbItem>
        <BreadcrumbItem href={`/space/${spaceId}`}>
          {space?.space_name || spaceId}
        </BreadcrumbItem>
        <BreadcrumbItem href={`/space/${spaceId}/graph/${graphId}`}>
          {graph?.graph_name || `Graph ${graphId}`}
        </BreadcrumbItem>
        <BreadcrumbItem>
          Analysis
        </BreadcrumbItem>
      </Breadcrumb>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
            Graph Analysis
          </h1>
          <p className="text-gray-600 dark:text-gray-400 mt-1">
            Analysis for {graph?.graph_name} in {space?.space_name}
          </p>
        </div>
        <div className="flex items-center">
          <HiChartBar className="h-8 w-8 text-purple-600 dark:text-purple-400" />
        </div>
      </div>

      {/* Type Distribution Chart */}
      <Card>
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
            Entity Type Distribution
          </h2>
          <div className="text-sm text-gray-500 dark:text-gray-400">
            Total: {mockGraphTypeData.reduce((sum, item) => sum + item.count, 0)} entities
          </div>
        </div>
        
        <div className="space-y-4">
          {mockGraphTypeData.map((item, index) => (
            <div key={index} className="flex items-center space-x-4">
              <div className="w-24 text-sm font-medium text-gray-700 dark:text-gray-300 text-right">
                {item.type}
              </div>
              <div className="flex-1 relative">
                <div className="h-8 bg-gray-200 dark:bg-gray-700 rounded-lg overflow-hidden">
                  <div
                    className="h-full rounded-lg transition-all duration-300 ease-in-out flex items-center justify-end pr-3"
                    style={{
                      backgroundColor: item.color,
                      width: `${(item.count / maxCount) * 100}%`,
                      minWidth: '60px'
                    }}
                  >
                    <span className="text-white text-sm font-medium">
                      {item.count}
                    </span>
                  </div>
                </div>
              </div>
              <div className="w-16 text-sm text-gray-500 dark:text-gray-400 text-right">
                {((item.count / mockGraphTypeData.reduce((sum, i) => sum + i.count, 0)) * 100).toFixed(1)}%
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Summary Statistics */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card>
          <div className="text-center">
            <div className="text-3xl font-bold text-blue-600 dark:text-blue-400">
              {mockGraphTypeData.reduce((sum, item) => sum + item.count, 0)}
            </div>
            <div className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              Total Entities
            </div>
          </div>
        </Card>
        
        <Card>
          <div className="text-center">
            <div className="text-3xl font-bold text-green-600 dark:text-green-400">
              {mockGraphTypeData.length}
            </div>
            <div className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              Entity Types
            </div>
          </div>
        </Card>
        
        <Card>
          <div className="text-center">
            <div className="text-3xl font-bold text-purple-600 dark:text-purple-400">
              {Math.round(mockGraphTypeData.reduce((sum, item) => sum + item.count, 0) / mockGraphTypeData.length)}
            </div>
            <div className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              Avg per Type
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
};

export default GraphAnalysis;
