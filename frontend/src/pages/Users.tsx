import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { apiService } from '../services/ApiService';
import { Alert, Badge, TextInput } from 'flowbite-react';
import { HiSearch, HiUser, HiChevronRight, HiUserGroup } from 'react-icons/hi';
import { SkeletonTable } from '../components/Skeleton';
import { usePageTitle } from '../hooks/usePageTitle';
import TimeAgo from '../components/TimeAgo';

interface User {
  id: string;
  username: string;
  full_name: string;
  email: string;
  profile_image?: string;
  role: string;
  tenant?: string;
  update_time?: string;
}

const roleBadge = (role: string) => {
  const r = role?.toLowerCase() || '';
  if (r === 'admin') return <Badge color="purple">Admin</Badge>;
  if (r === 'editor') return <Badge color="info">Editor</Badge>;
  if (r === 'viewer') return <Badge color="gray">Viewer</Badge>;
  return <Badge color="gray">{role || 'Unknown'}</Badge>;
};


const Users: React.FC = () => {
  usePageTitle('Users');
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterText, setFilterText] = useState('');

  const fetchUsers = useCallback(async () => {
    try {
      setLoading(true);
      const data = await apiService.getUsers();
      setUsers(data);
      setError(null);
    } catch {
      setError('Failed to load users.');
      setUsers([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const filteredUsers = filterText
    ? users.filter((u) => {
        const term = filterText.toLowerCase();
        return (
          u.username.toLowerCase().includes(term) ||
          (u.full_name || '').toLowerCase().includes(term) ||
          (u.email || '').toLowerCase().includes(term) ||
          (u.role || '').toLowerCase().includes(term)
        );
      })
    : users;

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-2">
          <HiUserGroup className="w-6 h-6 text-blue-600" />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Users</h1>
        </div>
        <SkeletonTable rows={5} cols={4} />
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="users-page">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <HiUserGroup className="w-6 h-6 text-blue-600" />
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Users</h1>
          </div>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            {users.length} user{users.length !== 1 ? 's' : ''}
          </p>
        </div>
        <div className="w-full sm:w-72">
          <TextInput
            icon={HiSearch}
            placeholder="Search users..."
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
          />
        </div>
      </div>

      {error && (
        <Alert color="failure" onDismiss={() => setError(null)}>
          <span className="font-medium">Error:</span> {error}
        </Alert>
      )}

      {filteredUsers.length === 0 && !error ? (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">
          <HiUser className="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          {filterText ? (
            <>
              <p className="text-lg font-medium">No users match &quot;{filterText}&quot;</p>
              <p className="text-sm mt-1">Try a different search term</p>
            </>
          ) : (
            <>
              <p className="text-lg font-medium">No users yet</p>
              <p className="text-sm mt-1">Create your first user to get started</p>
            </>
          )}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-gray-500 dark:text-gray-400 uppercase bg-gray-50 dark:bg-gray-800">
              <tr>
                <th className="px-4 py-3">User</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3 hidden md:table-cell">Email</th>
                <th className="px-4 py-3 hidden lg:table-cell">Tenant</th>
                <th className="px-4 py-3 hidden lg:table-cell">Updated</th>
                <th className="px-4 py-3 w-10"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
              {filteredUsers.map((user) => (
                <tr key={user.id} className="bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                  <td className="px-4 py-3">
                    <Link to={`/user/${user.id}`} className="group">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900 flex items-center justify-center flex-shrink-0">
                          {user.profile_image ? (
                            <img src={user.profile_image} alt="" className="w-8 h-8 rounded-full" />
                          ) : (
                            <span className="text-xs font-semibold text-blue-600 dark:text-blue-400">
                              {(user.username || '?')[0].toUpperCase()}
                            </span>
                          )}
                        </div>
                        <div className="min-w-0">
                          <p className="font-medium text-gray-900 dark:text-white truncate group-hover:text-blue-600 transition-colors">
                            {user.username}
                          </p>
                          {user.full_name && (
                            <p className="text-xs text-gray-500 dark:text-gray-400 truncate">{user.full_name}</p>
                          )}
                        </div>
                      </div>
                    </Link>
                  </td>
                  <td className="px-4 py-3">{roleBadge(user.role)}</td>
                  <td className="px-4 py-3 hidden md:table-cell text-gray-500 dark:text-gray-400">
                    {user.email || '—'}
                  </td>
                  <td className="px-4 py-3 hidden lg:table-cell text-gray-500 dark:text-gray-400">
                    {user.tenant || '—'}
                  </td>
                  <td className="px-4 py-3 hidden lg:table-cell text-gray-500 dark:text-gray-400 text-xs">
                    <TimeAgo date={user.update_time} />
                  </td>
                  <td className="px-4 py-3">
                    <Link
                      to={`/user/${user.id}`}
                      className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-blue-500 transition-colors inline-flex"
                    >
                      <HiChevronRight className="w-4 h-4" />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default Users;
