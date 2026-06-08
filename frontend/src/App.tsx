import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { initThemeMode, Spinner } from 'flowbite-react';
import { AuthProvider } from './contexts/AuthContext';
import { WebSocketProvider } from './contexts/WebSocketContext';
import { ChangeNotificationProvider } from './contexts/ChangeNotificationContext';
import { ToastProvider } from './contexts/ToastContext';
import ToastContainer from './components/ToastContainer';
import WebSocketManager from './components/WebSocketManager';
import TopLoader from './components/TopLoader';
import ScrollToTop from './components/ScrollToTop';
import ErrorBoundary from './components/ErrorBoundary';
import ProtectedRoute from './components/auth/ProtectedRoute';
import Layout from './components/Layout';

// Lazy-loaded pages for code-splitting
const Login = lazy(() => import('./pages/Login'));
const Home = lazy(() => import('./pages/Home'));
const Spaces = lazy(() => import('./pages/Spaces'));
const SpaceDetail = lazy(() => import('./pages/SpaceDetail'));
const Users = lazy(() => import('./pages/Users'));
const UserDetail = lazy(() => import('./pages/UserDetail'));
const Files = lazy(() => import('./pages/Files'));
const FileDetail = lazy(() => import('./pages/FileDetail'));
const FileUpload = lazy(() => import('./pages/FileUpload'));
const Graphs = lazy(() => import('./pages/Graphs'));
const GraphDetail = lazy(() => import('./pages/GraphDetail'));
const KGTypes = lazy(() => import('./pages/KGTypes'));
const KGTypeDetail = lazy(() => import('./pages/KGTypeDetail'));
const ObjectsLayout = lazy(() => import('./pages/ObjectsLayout'));
const GraphObjects = lazy(() => import('./pages/GraphObjects'));
const KGEntities = lazy(() => import('./pages/KGEntities'));
const KGFrames = lazy(() => import('./pages/KGFrames'));
const ObjectDetail = lazy(() => import('./pages/ObjectDetail'));
const KGEntityDetail = lazy(() => import('./pages/KGEntityDetail'));
const KGFrameDetail = lazy(() => import('./pages/KGFrameDetail'));
const Triples = lazy(() => import('./pages/Triples'));
const SPARQL = lazy(() => import('./pages/SPARQL'));
const Data = lazy(() => import('./pages/Data'));
const DataImportDetail = lazy(() => import('./pages/DataImportDetail'));
const DataExportDetail = lazy(() => import('./pages/DataExportDetail'));
const VectorIndexes = lazy(() => import('./pages/VectorIndexes'));
const VectorMappings = lazy(() => import('./pages/VectorMappings'));
const VectorMappingDetail = lazy(() => import('./pages/VectorMappingDetail'));
const VectorSearch = lazy(() => import('./pages/VectorSearch'));
const GeoPoints = lazy(() => import('./pages/GeoPoints'));
const ApiKeys = lazy(() => import('./pages/ApiKeys'));
const Admin = lazy(() => import('./pages/Admin'));
const AuditLog = lazy(() => import('./pages/AuditLog'));
const EntityRegistry = lazy(() => import('./pages/EntityRegistry'));
const EntityRegistryDetail = lazy(() => import('./pages/EntityRegistryDetail'));
const AgentRegistry = lazy(() => import('./pages/AgentRegistry'));
const AgentRegistryDetail = lazy(() => import('./pages/AgentRegistryDetail'));
const KGRelations = lazy(() => import('./pages/KGRelations'));
const KGQueryBuilder = lazy(() => import('./pages/KGQueryBuilder'));
const NotFound = lazy(() => import('./pages/NotFound'));

const PageLoader = () => (
  <>
    <TopLoader />
    <div className="flex justify-center items-center min-h-[60vh]">
      <Spinner size="xl" />
    </div>
  </>
);

// Initialize theme mode
initThemeMode();

export default function App() {
  return (
    <ErrorBoundary>
    <AuthProvider>
      <WebSocketProvider>
        <ToastProvider>
        <WebSocketManager />
        <BrowserRouter>
          <ScrollToTop />
          <ChangeNotificationProvider>
            <Suspense fallback={<PageLoader />}>
            <Routes>
          {/* Public routes */}
          <Route path="/login" element={<Login />} />
          
          {/* Protected routes - must be authenticated */}
          <Route element={<ProtectedRoute />}>
            <Route element={<Layout />}>
              <Route path="/" element={<Home />} />
              <Route path="/spaces" element={<Spaces />} />
              <Route path="/users" element={<Users />} />
              <Route path="/data" element={<Navigate to="/data/import" replace />} />
              <Route path="/sparql" element={<SPARQL />} />
              
              {/* Base selection screens */}
              <Route path="/graphs" element={<Graphs />} />
              <Route path="/objects" element={<Navigate to="/objects/graphobjects" replace />} />
              <Route path="/objects/*" element={<ObjectsLayout />}>
                <Route path="graphobjects" element={<GraphObjects />} />
                <Route path="kgentities" element={<KGEntities />} />
                <Route path="kgframes" element={<KGFrames />} />
                <Route path="kgrelations" element={<KGRelations />} />
              </Route>
              <Route path="/files" element={<Files />} />
              <Route path="/triples" element={<Triples />} />
              <Route path="/kg-types" element={<KGTypes />} />
              <Route path="/kg-query-builder" element={<KGQueryBuilder />} />
              
              {/* Hierarchical routes */}
              <Route path="/space/:spaceId/graphs" element={<Graphs />} />
              <Route path="/space/:spaceId/graph/:graphId/objects" element={<Navigate to="graphobjects" replace />} />
              <Route path="/space/:spaceId/graph/:graphId/objects/*" element={<ObjectsLayout />}>
                <Route path="graphobjects" element={<GraphObjects />} />
                <Route path="kgentities" element={<KGEntities />} />
                <Route path="kgframes" element={<KGFrames />} />
                <Route path="kgrelations" element={<KGRelations />} />
              </Route>
              <Route path="/space/:spaceId/graph/:graphId/files" element={<Files />} />
              <Route path="/space/:spaceId/graph/:graphId/triples" element={<Triples />} />
              <Route path="/space/:spaceId/graph/:graphId/kg-types" element={<KGTypes />} />
              
              {/* Creation routes */}
              <Route path="/space/:spaceId/graph/new" element={<GraphDetail />} />
              <Route path="/space/:spaceId/graph/:graphId/file/new" element={<FileUpload />} />
              
              {/* Data routes */}
              <Route path="/data/import" element={<Data />} />
              <Route path="/data/export" element={<Data />} />
              <Route path="/data/import/new" element={<DataImportDetail />} />
              <Route path="/data/import/:importId" element={<DataImportDetail />} />
              <Route path="/data/export/new" element={<DataExportDetail />} />
              <Route path="/data/export/:exportId" element={<DataExportDetail />} />
              
              {/* Admin routes */}
              <Route path="/api-keys" element={<ApiKeys />} />
              <Route path="/admin" element={<Admin />} />
              <Route path="/audit-log" element={<AuditLog />} />
              <Route path="/entity-registry" element={<EntityRegistry />} />
              <Route path="/entity-registry/:entityId" element={<EntityRegistryDetail />} />
              <Route path="/agent-registry" element={<AgentRegistry />} />
              <Route path="/agent-registry/:agentId" element={<AgentRegistryDetail />} />
              
              {/* Vector/Geo routes */}
              <Route path="/vector-indexes" element={<VectorIndexes />} />
              <Route path="/vector-mappings" element={<VectorMappings />} />
              <Route path="/space/:spaceId/vector-mappings/:mappingId" element={<VectorMappingDetail />} />
              <Route path="/vector-search" element={<VectorSearch />} />
              <Route path="/geo-points" element={<GeoPoints />} />
              
              {/* Detail routes */}
              <Route path="/space/:id" element={<SpaceDetail />} />
              <Route path="/space/:spaceId/graph/:graphId" element={<GraphDetail />} />
              <Route path="/space/:spaceId/graph/:graphId/object/:objectId" element={<ObjectDetail />} />
              <Route path="/space/:spaceId/graph/:graphId/entity/:entityId" element={<KGEntityDetail />} />
              <Route path="/space/:spaceId/graph/:graphId/frame/:frameId" element={<KGFrameDetail />} />
              <Route path="/space/:spaceId/graph/:graphId/kg-types/new" element={<KGTypeDetail />} />
              <Route path="/space/:spaceId/graph/:graphId/kg-types/:kgTypeId" element={<KGTypeDetail />} />
              <Route path="/space/:spaceId/graph/:graphId/objects/new" element={<ObjectDetail />} />
              <Route path="/space/:spaceId/graph/:graphId/objects/:objectId" element={<ObjectDetail />} />
              <Route path="/space/:spaceId/graph/:graphId/file/:fileId" element={<FileDetail />} />
              <Route path="/user/:id" element={<UserDetail />} />
            </Route>
          </Route>
          
          {/* 404 */}
          <Route path="*" element={<NotFound />} />
            </Routes>
            </Suspense>
          </ChangeNotificationProvider>
        </BrowserRouter>
        <ToastContainer />
        </ToastProvider>
      </WebSocketProvider>
    </AuthProvider>
    </ErrorBoundary>
  );
}
