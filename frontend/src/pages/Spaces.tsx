import React, { useState, useEffect, useCallback, useRef, useLayoutEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { Alert, Button, Card, Spinner, Table, TableBody, TableCell, TableHead, TableHeadCell, TableRow, TextInput } from 'flowbite-react';
import { HiSearch, HiEye, HiPlus } from 'react-icons/hi';

interface Space {
  id: number;
  tenant: string;
  space: string;
  space_name: string;
  space_description: string;
  update_time: string;
}

const Spaces: React.FC = () => {
  const navigate = useNavigate();
  const filterInputRef = useRef<HTMLInputElement>(null);
  const cursorPositionRef = useRef<number>(0);
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [filterText, setFilterText] = useState<string>('');
  const [filterLoading, setFilterLoading] = useState<boolean>(false);

  // Fetch all spaces
  const fetchSpaces = useCallback(async () => {
    try {
      setLoading(true);
      const response = await axios.get('/api/spaces');
      // Handle both array response and wrapped response
      const spacesData = Array.isArray(response.data) ? response.data : response.data.spaces || [];
      setSpaces(spacesData);
      setError(null);
    } catch (err) {
      console.error('Error fetching spaces:', err);
      setError('Failed to load spaces. Please try again later.');
      setSpaces([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // Filter spaces by name
  const filterSpaces = useCallback(async (nameFilter: string) => {
    if (!nameFilter.trim()) {
      // If filter is empty and not already loading data, fetch all spaces
      // This prevents duplicate API calls on initial page load
      if (loading) {
        // Don't trigger another fetch if we're already loading data
        return;
      }
      await fetchSpaces();
      return;
    }

    try {
      setFilterLoading(true);
      const response = await axios.get(`/api/spaces/filter/${encodeURIComponent(nameFilter)}`);
      // Handle both array response and wrapped response
      const spacesData = Array.isArray(response.data) ? response.data : response.data.spaces || [];
      setSpaces(spacesData);
      setError(null);
    } catch (err) {
      console.error('Error filtering spaces:', err);
      setError('Failed to filter spaces. Please try again later.');
      setSpaces([]);
    } finally {
      setFilterLoading(false);
    }
  }, [fetchSpaces]);

  // Restore focus and cursor position after renders
  useLayoutEffect(() => {
    if (filterInputRef.current && document.activeElement !== filterInputRef.current) {
      filterInputRef.current.focus();
      filterInputRef.current.setSelectionRange(cursorPositionRef.current, cursorPositionRef.current);
    }
  });

  // Handle filter input change with debouncing
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      filterSpaces(filterText);
    }, 500); // 500ms debounce

    return () => clearTimeout(timeoutId);
  }, [filterText, filterSpaces]);

  // Initial load
  useEffect(() => {
    fetchSpaces();
  }, [fetchSpaces]);

  const handleDetailsClick = (space: Space) => {
    navigate(`/space/${space.id}`);
  };

  const formatDate = (dateString: string) => {
    try {
      return new Date(dateString).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch {
      return dateString;
    }
  };

  if (loading && !filterLoading) {
    return (
      <div className="flex justify-center items-center h-40">
        <Spinner size="xl" />
      </div>
    );
  }

  return (
    <div>
      <div className="mb-6">
        <div className="flex justify-between items-start">
          <div>
            <h1 className="mb-2 text-2xl font-bold text-gray-900 dark:text-white">Spaces</h1>
            <p className="text-gray-500 dark:text-gray-400">
              View and manage your VitalGraph spaces.
            </p>
          </div>
          <Button color="blue" onClick={() => navigate('/space/new')}>
            <HiPlus className="mr-2 h-4 w-4" />
            Add Space
          </Button>
        </div>
      </div>

      {/* Filter Section */}
      <div className="mb-6">
        <div className="relative max-w-md">
          <TextInput
            ref={filterInputRef}
            id="filter"
            type="text"
            icon={HiSearch}
            placeholder="Filter spaces by name..."
            value={filterText}
            onChange={(e) => {
              cursorPositionRef.current = e.target.selectionStart || 0;
              setFilterText(e.target.value);
            }}
            disabled={filterLoading}
          />
          {filterLoading && (
            <div className="absolute right-3 top-1/2 transform -translate-y-1/2">
              <Spinner size="sm" />
            </div>
          )}
        </div>
        {filterText && (
          <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
            {filterLoading ? 'Filtering...' : `Showing results for "${filterText}"`}
          </p>
        )}
      </div>

      {/* Error Display */}
      {error && (
        <Alert color="failure" className="mb-6">
          <span className="font-medium">Error:</span> {error}
        </Alert>
      )}

      {/* Spaces Table */}
      {spaces.length === 0 && !loading && !error ? (
        <Alert color="info">
          {filterText ? 
            `No spaces found matching "${filterText}". Try a different search term.` :
            'No spaces found. Create your first space to get started.'
          }
        </Alert>
      ) : (
        <>
          {/* Desktop Table View */}
          <div className="hidden md:block overflow-x-auto">
            <Table striped>
              <TableHead>
                <TableRow>
                  <TableHeadCell>ID</TableHeadCell>
                  <TableHeadCell>Name</TableHeadCell>
                  <TableHeadCell>Space ID</TableHeadCell>
                  <TableHeadCell>Tenant</TableHeadCell>
                  <TableHeadCell>Description</TableHeadCell>
                  <TableHeadCell>Last Updated</TableHeadCell>
                  <TableHeadCell>Actions</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody className="divide-y">
                {spaces.map((space) => (
                  <TableRow key={space.id} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                    <TableCell className="whitespace-nowrap font-medium text-gray-900 dark:text-white">
                      {space.id}
                    </TableCell>
                    <TableCell className="font-medium text-gray-900 dark:text-white">
                      {space.space_name}
                    </TableCell>
                    <TableCell className="text-gray-500 dark:text-gray-400">
                      {space.space}
                    </TableCell>
                    <TableCell className="text-gray-500 dark:text-gray-400">
                      {space.tenant}
                    </TableCell>
                    <TableCell className="text-gray-500 dark:text-gray-400">
                      {space.space_description || 'No description'}
                    </TableCell>
                    <TableCell className="text-gray-500 dark:text-gray-400">
                      {formatDate(space.update_time)}
                    </TableCell>
                    <TableCell>
                      <Button
                        size="sm"
                        color="blue"
                        onClick={() => handleDetailsClick(space)}
                      >
                        <HiEye className="mr-2 h-4 w-4" />
                        Details
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {/* Mobile Card View */}
          <div className="md:hidden space-y-4">
            {spaces.map((space) => (
              <Card key={space.id} className="w-full">
                <div className="space-y-3">
                  <div className="flex justify-between items-start">
                    <div>
                      <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                        {space.space_name}
                      </h3>
                      <p className="text-sm text-gray-500 dark:text-gray-400">
                        ID: {space.id} • Space ID: {space.space}
                      </p>
                    </div>
                    <Button
                      size="sm"
                      color="blue"
                      onClick={() => handleDetailsClick(space)}
                    >
                      <HiEye className="mr-1 h-4 w-4" />
                      Details
                    </Button>
                  </div>
                  
                  <div className="grid grid-cols-1 gap-2 text-sm">
                    <div>
                      <span className="font-medium text-gray-700 dark:text-gray-300">Tenant:</span>
                      <span className="ml-2 text-gray-600 dark:text-gray-400">{space.tenant}</span>
                    </div>
                    
                    <div>
                      <span className="font-medium text-gray-700 dark:text-gray-300">Description:</span>
                      <span className="ml-2 text-gray-600 dark:text-gray-400">
                        {space.space_description || 'No description'}
                      </span>
                    </div>
                    
                    <div>
                      <span className="font-medium text-gray-700 dark:text-gray-300">Last Updated:</span>
                      <span className="ml-2 text-gray-600 dark:text-gray-400">
                        {formatDate(space.update_time)}
                      </span>
                    </div>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </>
      )}
    </div>
  );
};

export default Spaces;
