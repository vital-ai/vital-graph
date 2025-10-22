import React from 'react';
import {
  Button,
  Card,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeadCell,
  TableRow,
  Badge,
  Modal,
  TextInput,
  Alert,
  Spinner,
  Select,
  Label
} from 'flowbite-react';
import { 
  HiTrash, 
  HiPlus,
  HiPencil
} from 'react-icons/hi2';
import { HiSave, HiX } from 'react-icons/hi';
import NavigationBreadcrumb from './NavigationBreadcrumb';
import { ObjectDetailConfig, BaseRDFObject } from '../pages/AbsObjectDetail';

interface ObjectDetailRendererProps<T extends BaseRDFObject = BaseRDFObject> {
  config: ObjectDetailConfig;
  object: T | null;
  loading: boolean;
  saving: boolean;
  error: string | null;
  showDeleteObjectModal: boolean;
  newProperty: {
    predicate: string;
    value: string;
    type: 'uri' | 'literal';
  };
  spaceId: string | undefined;
  graphId: string | undefined;
  mode: string;
  isCreateMode: boolean;
  // Functions
  setShowDeleteObjectModal: (show: boolean) => void;
  setNewProperty: (prop: { predicate: string; value: string; type: 'uri' | 'literal' }) => void;
  setSearchParams: (params: any) => void;
  navigate: (path: any) => void;
  extractLocalName: (uri: string) => string;
  formatDateTime: (dateString: string) => string;
  getObjectTypeBadge: (type: string) => React.ReactElement;
  updateProperty: (index: number, field: 'predicate' | 'object' | 'object_type', value: string | 'uri' | 'literal') => void;
  removeProperty: (index: number) => void;
  handleAddProperty: () => void;
  handleSave: () => void;
  getPageTitle: () => string;
  getObjectDisplayName: () => string;
}

export function ObjectDetailRenderer<T extends BaseRDFObject = BaseRDFObject>(props: ObjectDetailRendererProps<T>) {
  const {
    config,
    object,
    loading,
    saving,
    error,
    showDeleteObjectModal,
    newProperty,
    spaceId,
    graphId,
    mode,
    isCreateMode,
    setShowDeleteObjectModal,
    setNewProperty,
    setSearchParams,
    navigate,
    extractLocalName,
    formatDateTime,
    getObjectTypeBadge,
    updateProperty,
    removeProperty,
    handleAddProperty,
    handleSave,
    getPageTitle,
    getObjectDisplayName
  } = props;

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <Spinner size="xl" />
        <span className="ml-3 text-lg text-gray-600 dark:text-gray-400">
          Loading {config.objectTypeName.toLowerCase()} details...
        </span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <Alert color="failure" className="mb-4">
          <span>{error}</span>
        </Alert>
        <Button color="blue" onClick={() => navigate(-1)}>
          Go Back
        </Button>
      </div>
    );
  }

  if (!object) {
    return (
      <div className="p-6">
        <div className="text-center py-12">
          <p className="text-lg text-gray-600 dark:text-gray-400 mb-4">
            {config.objectTypeName} not found
          </p>
          <Button color="blue" onClick={() => navigate(-1)}>
            Go Back
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Navigation Breadcrumb */}
      <NavigationBreadcrumb 
        spaceId={spaceId} 
        graphId={graphId} 
        currentPageName={getPageTitle()}
        currentPageIcon={config.icon as any}
      />

      {/* Header with Mode Controls */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button
            color="gray"
            size="sm"
            onClick={() => {
              const encodedGraphId = encodeURIComponent(graphId || '');
              const backUrl = `/space/${spaceId}/graph/${encodedGraphId}${config.listRoute}`;
              console.log('Navigating back to:', backUrl);
              console.log('Original graphId:', graphId);
              console.log('Encoded graphId:', encodedGraphId);
              navigate(backUrl);
            }}
          >
            ← Back to {config.objectTypeName}s
          </Button>
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
              {getPageTitle()}
            </h1>
            <p className="text-gray-600 dark:text-gray-400">
              {getObjectDisplayName()}
            </p>
          </div>
        </div>

        <div className="flex gap-2">
          {mode === 'view' && !isCreateMode && (
            <Button
              color="blue"
              onClick={() => setSearchParams({ mode: 'edit' })}
            >
              <HiPencil className="w-4 h-4 mr-2" />
              Edit
            </Button>
          )}
          {(mode === 'edit' || isCreateMode) && (
            <>
              <Button
                color="gray"
                onClick={() => isCreateMode ? navigate(`/space/${spaceId}/graph/${encodeURIComponent(graphId || '')}${config.listRoute}`) : setSearchParams({ mode: 'view' })}
              >
                <HiX className="w-4 h-4 mr-2" />
                Cancel
              </Button>
              <Button
                color="green"
                onClick={handleSave}
                disabled={saving}
              >
                {saving ? (
                  <Spinner size="sm" className="mr-2" />
                ) : (
                  <HiSave className="w-4 h-4 mr-2" />
                )}
                {isCreateMode ? 'Create' : 'Save'}
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Error Alert */}
      {error && (
        <Alert color="failure">
          {error}
        </Alert>
      )}

      {/* Object Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
        <div className="flex items-center gap-2">
          {React.createElement(config.icon, { className: `w-8 h-8 text-${config.objectTypeColor}-600` })}
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">
            {extractLocalName(object?.object_uri || '')}
          </h1>
          <div className="flex items-center gap-3">
            {getObjectTypeBadge(object?.object_type || 'Node')}
            <Badge color="info">{extractLocalName(object?.rdf_type || '')}</Badge>
          </div>
        </div>

        <div className="flex gap-4">
          <Button color="red" onClick={() => setShowDeleteObjectModal(true)}>
            <HiTrash className="mr-2 h-4 w-4" />
            Delete {config.objectTypeName}
          </Button>
        </div>
      </div>

      {/* Basic Information */}
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-4">Basic Information</h2>
        <Card>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">Space:</span>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {spaceId || 'Unknown Space'}
              </p>
            </div>
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">{config.uriFieldName}:</span>
              <p className="text-sm text-gray-600 dark:text-gray-400 font-mono break-all">
                {object?.object_uri || ''}
              </p>
            </div>
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">RDF Type:</span>
              <p className="text-sm text-gray-600 dark:text-gray-400 font-mono break-all">
                {object?.rdf_type || ''}
              </p>
            </div>
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">Context:</span>
              <p className="text-sm text-gray-600 dark:text-gray-400 font-mono break-all">
                {object?.context || ''}
              </p>
            </div>
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">Object Type:</span>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {getObjectTypeBadge(object?.object_type || 'Node')}
              </p>
            </div>
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">Properties Count:</span>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {object?.properties_count || 0} properties
              </p>
            </div>
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">Created:</span>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {formatDateTime(object?.created_time || '')}
              </p>
            </div>
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">Last Modified:</span>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {formatDateTime(object?.last_modified || '')}
              </p>
            </div>
          </div>
        </Card>
      </div>

      {/* Properties */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-gray-900 dark:text-white">
            Properties
          </h2>
        </div>
        {mode === 'view' ? (
          // View Mode - Read-only display
          <Card>
            <div className="overflow-x-auto">
              <Table>
                <TableHead>
                  <TableRow>
                    <TableHeadCell>Predicate</TableHeadCell>
                    <TableHeadCell>Object</TableHeadCell>
                    <TableHeadCell>Type</TableHeadCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(object?.properties || []).map((prop: any, index: number) => (
                    <TableRow key={index}>
                      <TableCell className="font-mono text-sm break-all">{prop.predicate}</TableCell>
                      <TableCell className="text-sm break-all">{prop.object}</TableCell>
                      <TableCell>
                        <Badge color={prop.object_type === 'uri' ? 'blue' : 'green'}>
                          {prop.object_type}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Card>
        ) : (
          // Edit/Create Mode - Editable display with persistent add form
          <Card>
            {/* Add Property Form - Always visible at top in edit/create mode */}
            <div className="mb-6 p-4 bg-gray-50 dark:bg-gray-700 rounded-lg">
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-end">
                <div>
                  <Label htmlFor="new-predicate">Property Name</Label>
                  <TextInput
                    id="new-predicate"
                    placeholder="Enter property name"
                    value={newProperty.predicate}
                    onChange={(e) => setNewProperty({ ...newProperty, predicate: e.target.value })}
                  />
                </div>
                <div>
                  <Label htmlFor="new-value">Property Value</Label>
                  <TextInput
                    id="new-value"
                    placeholder="Enter property value"
                    value={newProperty.value}
                    onChange={(e) => setNewProperty({ ...newProperty, value: e.target.value })}
                  />
                </div>
                <div>
                  <Label htmlFor="new-type">Type</Label>
                  <Select
                    id="new-type"
                    value={newProperty.type}
                    onChange={(e) => setNewProperty({ ...newProperty, type: e.target.value as 'uri' | 'literal' })}
                  >
                    <option value="literal">Literal</option>
                    <option value="uri">URI</option>
                  </Select>
                </div>
                <div>
                  <Button
                    color="blue"
                    onClick={handleAddProperty}
                    disabled={!newProperty.predicate || !newProperty.value}
                    className="w-full"
                  >
                    <HiPlus className="mr-2 h-4 w-4" />
                    Add
                  </Button>
                </div>
              </div>
            </div>

            {/* Properties Table with inline editing */}
            <div className="overflow-x-auto">
              <Table>
                <TableHead>
                  <TableRow>
                    <TableHeadCell>Predicate</TableHeadCell>
                    <TableHeadCell>Object</TableHeadCell>
                    <TableHeadCell>Type</TableHeadCell>
                    <TableHeadCell>Actions</TableHeadCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(object?.properties || []).map((prop: any, index: number) => (
                    <TableRow key={index}>
                      <TableCell>
                        <TextInput
                          value={prop.predicate}
                          onChange={(e) => updateProperty(index, 'predicate', e.target.value)}
                          className="font-mono text-sm"
                        />
                      </TableCell>
                      <TableCell>
                        <TextInput
                          value={prop.object}
                          onChange={(e) => updateProperty(index, 'object', e.target.value)}
                          className="text-sm"
                        />
                      </TableCell>
                      <TableCell>
                        <Select
                          value={prop.object_type}
                          onChange={(e) => updateProperty(index, 'object_type', e.target.value as 'uri' | 'literal')}
                        >
                          <option value="literal">Literal</option>
                          <option value="uri">URI</option>
                        </Select>
                      </TableCell>
                      <TableCell>
                        <Button
                          size="xs"
                          color="red"
                          onClick={() => removeProperty(index)}
                        >
                          <HiTrash className="h-3 w-3" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Card>
        )}
      </div>

      {/* Delete Object Modal */}
      <Modal show={showDeleteObjectModal} onClose={() => setShowDeleteObjectModal(false)}>
        <div className="p-6">
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">
            Delete {config.objectTypeName}
          </h3>
          <p className="text-gray-600 dark:text-gray-400 mb-6">
            Are you sure you want to delete this {config.objectTypeName.toLowerCase()}? This action cannot be undone.
          </p>
          <div className="flex justify-end gap-3">
            <Button color="red" onClick={() => {
              // TODO: Implement delete
              setShowDeleteObjectModal(false);
              navigate(-1);
            }}>
              Delete
            </Button>
            <Button color="gray" onClick={() => setShowDeleteObjectModal(false)}>
              Cancel
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
