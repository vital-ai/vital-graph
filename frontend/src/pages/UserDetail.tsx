import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { apiService } from '../services/ApiService';
import {
  Alert, Badge, Button, Card, Label, Select, TextInput, Spinner,
  Breadcrumb, BreadcrumbItem
} from 'flowbite-react';
import {
  HiPencil, HiTrash, HiSave, HiX, HiUser, HiHome,
  HiEye, HiEyeOff, HiUserGroup, HiShieldCheck, HiPlus, HiKey
} from 'react-icons/hi';
import { formatDateTimeFull } from '../utils/formatUtils';
import ConfirmDialog from '../components/ConfirmDialog';
import CopyButton from '../components/CopyButton';

interface User {
  id: string;
  username: string;
  full_name?: string;
  email?: string;
  profile_image?: string;
  role: string;
  is_active?: boolean;
  spaces?: Record<string, string>;
  created_time?: string;
  last_login?: string;
  update_time?: string;
}

const ROLES = ['admin', 'user', 'reader'] as const;

const roleBadge = (role: string) => {
  const r = role?.toLowerCase() || '';
  if (r === 'admin') return <Badge color="purple">Admin</Badge>;
  if (r === 'user') return <Badge color="info">User</Badge>;
  if (r === 'reader') return <Badge color="gray">Reader</Badge>;
  return <Badge color="gray">{role || 'Unknown'}</Badge>;
};

const formatDate = formatDateTimeFull;

// ─── Space Access Card ──────────────────────────────────────────────────────

interface SpaceAccessCardProps {
  username: string;
  onUpdate?: () => void;
}

const SpaceAccessCard: React.FC<SpaceAccessCardProps> = ({ username }) => {
  const [spaces, setSpaces] = useState<Record<string, string>>({});
  const [allSpaces, setAllSpaces] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [showGrant, setShowGrant] = useState(false);
  const [grantSpace, setGrantSpace] = useState('');
  const [grantLevel, setGrantLevel] = useState<'rw' | 'r'>('r');
  const [granting, setGranting] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchSpaces = useCallback(async () => {
    try {
      setLoading(true);
      const [accessData, spacesData] = await Promise.all([
        apiService.getUserSpaces(username),
        apiService.getSpaces(),
      ]);
      setSpaces(accessData.spaces || {});
      setAllSpaces(spacesData.map((s: { space: string }) => s.space));
    } catch {
      setError('Failed to load space access');
    } finally {
      setLoading(false);
    }
  }, [username]);

  useEffect(() => { fetchSpaces(); }, [fetchSpaces]);

  const handleGrant = async () => {
    if (!grantSpace) return;
    try {
      setGranting(true);
      setError(null);
      await apiService.grantSpaceAccess(username, grantSpace, grantLevel);
      setShowGrant(false);
      setGrantSpace('');
      setGrantLevel('r');
      await fetchSpaces();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to grant access');
    } finally {
      setGranting(false);
    }
  };

  const handleRevoke = async (spaceId: string) => {
    try {
      setRevoking(spaceId);
      setError(null);
      await apiService.revokeSpaceAccess(username, spaceId);
      await fetchSpaces();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to revoke access');
    } finally {
      setRevoking(null);
    }
  };

  const availableSpaces = allSpaces.filter(s => !(s in spaces));

  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Space Access</h2>
        <Button size="xs" color="blue" onClick={() => setShowGrant(!showGrant)}>
          <HiPlus className="mr-1 h-3 w-3" />Grant
        </Button>
      </div>

      {error && (
        <Alert color="failure" onDismiss={() => setError(null)} className="mb-3">
          {error}
        </Alert>
      )}

      {/* Grant form */}
      {showGrant && (
        <div className="flex flex-wrap items-end gap-2 mb-4 p-3 rounded-lg bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700">
          <div className="flex-1 min-w-[160px]">
            <Label htmlFor="grant-space" className="text-xs">Space</Label>
            <Select id="grant-space" sizing="sm" value={grantSpace} onChange={(e) => setGrantSpace(e.target.value)}>
              <option value="">Select space...</option>
              {availableSpaces.map(s => <option key={s} value={s}>{s}</option>)}
            </Select>
          </div>
          <div className="w-24">
            <Label htmlFor="grant-level" className="text-xs">Level</Label>
            <Select id="grant-level" sizing="sm" value={grantLevel} onChange={(e) => setGrantLevel(e.target.value as 'rw' | 'r')}>
              <option value="r">Read</option>
              <option value="rw">Read/Write</option>
            </Select>
          </div>
          <Button size="xs" color="blue" onClick={handleGrant} disabled={granting || !grantSpace}>
            {granting ? <Spinner size="xs" /> : 'Add'}
          </Button>
          <Button size="xs" color="gray" onClick={() => setShowGrant(false)}>Cancel</Button>
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-4"><Spinner size="sm" /></div>
      ) : Object.keys(spaces).length === 0 ? (
        <p className="text-sm text-gray-500 dark:text-gray-400">No space access configured.</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {Object.entries(spaces).map(([spaceId, accessLevel]) => (
            <div key={spaceId} className="flex items-center justify-between p-3 rounded-lg border border-gray-200 dark:border-gray-700">
              <div className="flex items-center gap-2 min-w-0">
                <Link to={`/space/${spaceId}`} className="text-sm text-blue-600 hover:underline truncate">{spaceId}</Link>
                <Badge color={accessLevel === 'rw' ? 'success' : 'info'} className="flex-shrink-0">
                  {accessLevel === 'rw' ? 'Read/Write' : 'Read'}
                </Badge>
              </div>
              <button
                onClick={() => handleRevoke(spaceId)}
                disabled={revoking === spaceId}
                className="ml-2 text-red-500 hover:text-red-700 disabled:opacity-50 flex-shrink-0"
                title="Revoke access"
              >
                {revoking === spaceId ? <Spinner size="xs" /> : <HiTrash className="h-4 w-4" />}
              </button>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
};

// ─── User API Keys Card ─────────────────────────────────────────────────────

interface UserApiKeysCardProps {
  username: string;
}

const UserApiKeysCard: React.FC<UserApiKeysCardProps> = ({ username }) => {
  const [keys, setKeys] = useState<{ key_id: string; prefix: string; name: string; is_active: boolean; created_time: string | null; last_used: string | null }[]>([]);
  const [loading, setLoading] = useState(true);
  const [revoking, setRevoking] = useState<string | null>(null);

  const fetchKeys = useCallback(async () => {
    try {
      setLoading(true);
      const data = await apiService.listApiKeys(username);
      setKeys((data.keys || []).filter((k: { username?: string }) => k.username === username));
    } catch {
      // Silently fail — keys endpoint might not be available
    } finally {
      setLoading(false);
    }
  }, [username]);

  useEffect(() => { fetchKeys(); }, [fetchKeys]);

  const handleRevoke = async (keyId: string) => {
    if (!window.confirm('Revoke this API key? This cannot be undone.')) return;
    try {
      setRevoking(keyId);
      await apiService.revokeApiKey(keyId);
      await fetchKeys();
    } catch {
      // ignore
    } finally {
      setRevoking(null);
    }
  };

  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
          <HiKey className="inline w-5 h-5 mr-1.5 text-yellow-500" />
          API Keys
        </h2>
      </div>

      {loading ? (
        <div className="flex justify-center py-4"><Spinner size="sm" /></div>
      ) : keys.length === 0 ? (
        <p className="text-sm text-gray-500 dark:text-gray-400">No API keys for this user.</p>
      ) : (
        <div className="space-y-2">
          {keys.map(k => (
            <div key={k.key_id} className="flex items-center justify-between p-3 rounded-lg border border-gray-200 dark:border-gray-700">
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-900 dark:text-white">{k.name}</p>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-xs font-mono text-gray-400">{k.prefix}...</span>
                  <CopyButton text={k.prefix} />
                  <Badge color={k.is_active ? 'success' : 'failure'} className="text-[10px]">
                    {k.is_active ? 'Active' : 'Revoked'}
                  </Badge>
                </div>
              </div>
              {k.is_active && (
                <button
                  onClick={() => handleRevoke(k.key_id)}
                  disabled={revoking === k.key_id}
                  className="ml-2 text-red-500 hover:text-red-700 disabled:opacity-50"
                  title="Revoke key"
                >
                  {revoking === k.key_id ? <Spinner size="xs" /> : <HiTrash className="h-4 w-4" />}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
};

// ─── Main Component ─────────────────────────────────────────────────────────

const UserDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const isCreating = id === 'new';

  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState(isCreating);
  const [saving, setSaving] = useState(false);
  const [banner, setBanner] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  // Edit form
  const [form, setForm] = useState({
    username: '',
    full_name: '',
    email: '',
    role: 'user',
    password: '',
  });

  useEffect(() => {
    const load = async () => {
      if (!id) { setError('User ID is required'); setLoading(false); return; }
      if (isCreating) { setLoading(false); return; }
      try {
        setLoading(true);
        const data = await apiService.getUser(id);
        setUser(data);
        setForm({
          username: data.username || '',
          full_name: data.full_name || '',
          email: data.email || '',
          role: data.role || 'user',
          password: '',
        });
        setError(null);
      } catch {
        setError('Failed to load user details');
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [id, isCreating]);

  const showBanner = (type: 'success' | 'error', message: string) => {
    setBanner({ type, message });
    setTimeout(() => setBanner(null), 5000);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      if (isCreating) {
        if (!form.username.trim() || !form.password.trim()) {
          showBanner('error', 'Username and password are required');
          setSaving(false);
          return;
        }
        const created = await apiService.createUser(form);
        showBanner('success', 'User created!');
        setTimeout(() => navigate(`/user/${created.id}`), 1000);
      } else {
        if (!user) return;
        const updateData: Record<string, string> = {};
        if (form.full_name !== (user.full_name || '')) updateData.full_name = form.full_name;
        if (form.email !== (user.email || '')) updateData.email = form.email;
        if (form.role !== (user.role || '')) updateData.role = form.role;
        if (form.password.trim()) updateData.password = form.password;

        const updated = await apiService.updateUser(user.id, updateData);
        setUser(updated);
        setForm({ ...form, password: '' });
        setIsEditing(false);
        showBanner('success', 'User updated!');
      }
    } catch (err) {
      showBanner('error', err instanceof Error ? err.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!user) return;
    try {
      await apiService.deleteUser(user.id);
      showBanner('success', 'User deleted');
      setTimeout(() => navigate('/users'), 1000);
    } catch {
      showBanner('error', 'Failed to delete user');
    }
    setShowDeleteModal(false);
  };

  const handleCancel = () => {
    if (isCreating) { navigate('/users'); return; }
    if (user) {
      setForm({
        username: user.username || '',
        full_name: user.full_name || '',
        email: user.email || '',
        role: user.role || 'user',
        password: '',
      });
    }
    setIsEditing(false);
  };

  const set = (field: keyof typeof form, value: string) => setForm(prev => ({ ...prev, [field]: value }));

  if (loading) {
    return <div className="flex justify-center items-center h-40"><Spinner size="xl" /></div>;
  }

  if (error) {
    return (
      <div className="space-y-4">
        <Alert color="failure"><span className="font-medium">Error:</span> {error}</Alert>
        <Link to="/users" className="text-blue-600 hover:underline text-sm">Back to Users</Link>
      </div>
    );
  }

  if (!user && !isCreating) {
    return (
      <div className="text-center py-16">
        <HiUser className="w-16 h-16 mx-auto mb-4 text-gray-300" />
        <p className="text-lg font-medium text-gray-500">User not found</p>
        <Link to="/users" className="text-blue-600 hover:underline text-sm mt-2 inline-block">Back to Users</Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <Breadcrumb>
        <BreadcrumbItem href="/" icon={HiHome}>Home</BreadcrumbItem>
        <BreadcrumbItem href="/users" icon={HiUserGroup}>Users</BreadcrumbItem>
        <BreadcrumbItem>{isCreating ? 'New User' : user?.username}</BreadcrumbItem>
      </Breadcrumb>

      {banner && (
        <Alert color={banner.type === 'success' ? 'success' : 'failure'} onDismiss={() => setBanner(null)}>
          {banner.message}
        </Alert>
      )}

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center gap-4">
          {!isCreating && user && (
            <div className="w-12 h-12 rounded-full bg-blue-100 dark:bg-blue-900 flex items-center justify-center flex-shrink-0">
              {user.profile_image ? (
                <img src={user.profile_image} alt="" className="w-12 h-12 rounded-full" />
              ) : (
                <span className="text-xl font-bold text-blue-600 dark:text-blue-400">
                  {(user.username || '?')[0].toUpperCase()}
                </span>
              )}
            </div>
          )}
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
              {isCreating ? 'Create User' : user?.username}
            </h1>
            {!isCreating && user && (
              <div className="flex items-center gap-2 mt-1">
                {roleBadge(user.role)}
                {user.is_active === false && <Badge color="failure">Inactive</Badge>}
              </div>
            )}
          </div>
        </div>
        <div className="flex gap-2 flex-shrink-0">
          {isEditing ? (
            <>
              <Button size="sm" color="blue" onClick={handleSave} disabled={saving}>
                <HiSave className="mr-1.5 h-4 w-4" />
                {saving ? 'Saving...' : isCreating ? 'Create' : 'Save'}
              </Button>
              <Button size="sm" color="gray" onClick={handleCancel} disabled={saving}>
                <HiX className="mr-1.5 h-4 w-4" />Cancel
              </Button>
            </>
          ) : (
            <>
              <Button size="sm" color="blue" onClick={() => setIsEditing(true)}>
                <HiPencil className="mr-1.5 h-4 w-4" />Edit
              </Button>
              <Button size="sm" color="failure" onClick={() => setShowDeleteModal(true)}>
                <HiTrash className="mr-1.5 h-4 w-4" />Delete
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Profile Section */}
      <Card>
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Profile</h2>
        {isEditing ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl">
            <div>
              <Label htmlFor="username">Username *</Label>
              <TextInput
                id="username"
                value={form.username}
                onChange={(e) => set('username', e.target.value)}
                placeholder="Enter username"
                disabled={!isCreating}
              />
              {!isCreating && <p className="text-xs text-gray-400 mt-1">Username cannot be changed</p>}
            </div>
            <div>
              <Label htmlFor="full_name">Full Name</Label>
              <TextInput
                id="full_name"
                value={form.full_name}
                onChange={(e) => set('full_name', e.target.value)}
                placeholder="Enter full name"
              />
            </div>
            <div>
              <Label htmlFor="email">Email</Label>
              <TextInput
                id="email"
                type="email"
                value={form.email}
                onChange={(e) => set('email', e.target.value)}
                placeholder="Enter email"
              />
            </div>
            <div>
              <Label htmlFor="role">Role</Label>
              <Select id="role" value={form.role} onChange={(e) => set('role', e.target.value)}>
                {ROLES.map(r => (
                  <option key={r} value={r}>{r.charAt(0).toUpperCase() + r.slice(1)}</option>
                ))}
              </Select>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Username</p>
              <p className="text-sm text-gray-900 dark:text-white">{user?.username}</p>
            </div>
            <div>
              <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Full Name</p>
              <p className="text-sm text-gray-900 dark:text-white">{user?.full_name || '—'}</p>
            </div>
            <div>
              <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Email</p>
              <p className="text-sm text-gray-900 dark:text-white">{user?.email || '—'}</p>
            </div>
            <div>
              <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Role</p>
              <div className="mt-0.5">{roleBadge(user?.role || '')}</div>
            </div>
          </div>
        )}
      </Card>

      {/* Security Section */}
      {isEditing && (
        <Card>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            <HiShieldCheck className="inline w-5 h-5 mr-1.5 text-green-500" />
            Security
          </h2>
          <div className="max-w-md">
            <Label htmlFor="password">{isCreating ? 'Password *' : 'New Password'}</Label>
            <div className="relative">
              <TextInput
                id="password"
                type={showPassword ? 'text' : 'password'}
                value={form.password}
                onChange={(e) => set('password', e.target.value)}
                placeholder={isCreating ? 'Enter password' : 'Leave blank to keep current'}
              />
              <button
                type="button"
                className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 hover:text-gray-600"
                onClick={() => setShowPassword(!showPassword)}
              >
                {showPassword ? <HiEyeOff className="h-5 w-5" /> : <HiEye className="h-5 w-5" />}
              </button>
            </div>
            {!isCreating && <p className="text-xs text-gray-400 mt-1">Only fill if you want to change the password</p>}
          </div>
        </Card>
      )}

      {/* Space Access */}
      {!isCreating && user && (
        <SpaceAccessCard username={user.username} onUpdate={() => { /* refresh handled internally */ }} />
      )}

      {/* API Keys */}
      {!isCreating && user && (
        <UserApiKeysCard username={user.username} />
      )}

      {/* Metadata */}
      {!isCreating && user && (
        <Card>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Metadata</h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <p className="text-sm font-medium text-gray-500 dark:text-gray-400">User ID</p>
              <p className="text-sm text-gray-900 dark:text-white font-mono">{user.id}</p>
            </div>
            <div>
              <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Created</p>
              <p className="text-sm text-gray-900 dark:text-white">{formatDate(user.created_time)}</p>
            </div>
            <div>
              <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Last Login</p>
              <p className="text-sm text-gray-900 dark:text-white">{formatDate(user.last_login)}</p>
            </div>
          </div>
        </Card>
      )}

      {/* Delete Modal */}
      <ConfirmDialog
        open={showDeleteModal}
        onConfirm={handleDelete}
        onCancel={() => setShowDeleteModal(false)}
        title="Delete User"
        description={<>Permanently delete <strong>{user?.username}</strong>?</>}
        confirmLabel="Delete"
        variant="danger"
      />
    </div>
  );
};

export default UserDetail;
