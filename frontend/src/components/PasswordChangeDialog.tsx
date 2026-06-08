import React, { useState } from 'react';
import {
  Modal,
  ModalHeader,
  ModalBody,
  ModalFooter,
  Button,
  Label,
  TextInput,
  Alert,
  Spinner,
} from 'flowbite-react';
import { HiKey, HiExclamationCircle } from 'react-icons/hi';
import { apiService } from '../services/ApiService';
import { useAuth } from '../contexts/AuthContext';

interface PasswordChangeDialogProps {
  show: boolean;
  onClose: () => void;
}

const PasswordChangeDialog: React.FC<PasswordChangeDialogProps> = ({ show, onClose }) => {
  const { logout } = useAuth();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const reset = () => {
    setCurrentPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setError(null);
    setLoading(false);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!currentPassword) {
      setError('Current password is required');
      return;
    }
    if (newPassword.length < 8) {
      setError('New password must be at least 8 characters');
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('New passwords do not match');
      return;
    }
    if (currentPassword === newPassword) {
      setError('New password must be different from current password');
      return;
    }

    try {
      setLoading(true);
      await apiService.changePassword(currentPassword, newPassword);
      // Password changed — tokens invalidated, log out
      reset();
      onClose();
      logout();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to change password');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal show={show} onClose={handleClose} size="md">
      <ModalHeader>
        <div className="flex items-center gap-2">
          <HiKey className="h-5 w-5 text-blue-600" />
          Change Password
        </div>
      </ModalHeader>
      <form onSubmit={handleSubmit}>
        <ModalBody>
          <div className="space-y-4">
            {error && (
              <Alert color="failure" icon={HiExclamationCircle}>
                {error}
              </Alert>
            )}

            <div>
              <Label htmlFor="current-password">Current Password</Label>
              <TextInput
                id="current-password"
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                placeholder="Enter current password"
                autoComplete="current-password"
                required
              />
            </div>

            <div>
              <Label htmlFor="new-password">New Password</Label>
              <TextInput
                id="new-password"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="Minimum 8 characters"
                autoComplete="new-password"
                required
              />
            </div>

            <div>
              <Label htmlFor="confirm-password">Confirm New Password</Label>
              <TextInput
                id="confirm-password"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Re-enter new password"
                autoComplete="new-password"
                required
              />
            </div>

            <p className="text-xs text-gray-500 dark:text-gray-400">
              After changing your password, you will be signed out and need to log in again.
            </p>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button type="submit" color="blue" disabled={loading}>
            {loading ? <><Spinner size="sm" className="mr-2" />Changing...</> : 'Change Password'}
          </Button>
          <Button color="gray" onClick={handleClose} disabled={loading}>
            Cancel
          </Button>
        </ModalFooter>
      </form>
    </Modal>
  );
};

export default PasswordChangeDialog;
