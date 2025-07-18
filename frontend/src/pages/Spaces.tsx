import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Alert, Card, Spinner } from 'flowbite-react';

interface Space {
  id: number;
  name: string;
  type: string;
}

const Spaces: React.FC = () => {
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchSpaces = async () => {
      try {
        const response = await axios.get('/api/spaces');
        setSpaces(response.data.spaces);
        setLoading(false);
      } catch (err) {
        console.error('Error fetching spaces:', err);
        setError('Failed to load spaces. Please try again later.');
        setLoading(false);
      }
    };

    fetchSpaces();
  }, []);

  if (loading) {
    return (
      <div className="flex justify-center items-center h-40">
        <Spinner size="xl" />
      </div>
    );
  }

  if (error) {
    return (
      <Alert color="failure">
        <span className="font-medium">Error:</span> {error}
      </Alert>
    );
  }

  return (
    <div>
      <h1 className="mb-4 text-xl font-bold text-gray-900 dark:text-white">Your Spaces</h1>
      <p className="mb-6 text-gray-500 dark:text-gray-400">
        View and manage your VitalGraph spaces.
      </p>
      
      {spaces.length === 0 ? (
        <Alert color="info">
          No spaces found. Create your first space to get started.
        </Alert>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {spaces.map((space) => (
            <Card key={space.id}>
              <h5 className="text-lg font-bold tracking-tight text-gray-900 dark:text-white">
                {space.name}
              </h5>
              <p className="font-normal text-gray-700 dark:text-gray-400">
                Type: {space.type}
              </p>
              <div className="flex justify-end">
                <button
                  className="px-4 py-2 text-sm font-medium text-white bg-blue-700 rounded-lg hover:bg-blue-800 focus:ring-4 focus:ring-blue-300 dark:bg-blue-600 dark:hover:bg-blue-700 focus:outline-none dark:focus:ring-blue-800"
                >
                  View Space
                </button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
};

export default Spaces;
