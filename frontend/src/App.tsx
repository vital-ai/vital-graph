import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { initThemeMode } from 'flowbite-react';
import { AuthProvider } from './contexts/AuthContext';
import { WebSocketProvider } from './contexts/WebSocketContext';
import { ChangeNotificationProvider } from './contexts/ChangeNotificationContext';
import WebSocketManager from './components/WebSocketManager';
import ProtectedRoute from './components/auth/ProtectedRoute';
import Layout from './components/Layout';
import Login from './pages/Login';
import Home from './pages/Home';
import Spaces from './pages/Spaces';
import SpaceDetail from './pages/SpaceDetail';
import Users from './pages/Users';
import UserDetail from './pages/UserDetail';
import Files from './pages/Files';
import FileDetail from './pages/FileDetail';
import FileUpload from './pages/FileUpload';
import Graphs from './pages/Graphs';
import GraphDetail from './pages/GraphDetail';
import GraphAnalysis from './pages/GraphAnalysis';
import KGTypes from './pages/KGTypes';
import KGTypeDetail from './pages/KGTypeDetail';
import ObjectsLayout from './pages/ObjectsLayout';
import GraphObjects from './pages/GraphObjects';
import KGEntities from './pages/KGEntities';
import KGFrames from './pages/KGFrames';
import ObjectDetail from './pages/ObjectDetail';
import KGEntityDetail from './pages/KGEntityDetail';
import KGFrameDetail from './pages/KGFrameDetail';
import Triples from './pages/Triples';
import SPARQL from './pages/SPARQL';
import Data from './pages/Data';
import DataImportDetail from './pages/DataImportDetail';
import DataExportDetail from './pages/DataExportDetail';
import DataMigrationDetail from './pages/DataMigrationDetail';
import DataTrackingDetail from './pages/DataTrackingDetail';
import DataCheckpointDetail from './pages/DataCheckpointDetail';

// Initialize theme mode
initThemeMode();

export default function App() {
  return (
    <AuthProvider>
      <WebSocketProvider>
        <WebSocketManager />
        <BrowserRouter>
          <ChangeNotificationProvider>
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
              </Route>
              <Route path="/files" element={<Files />} />
              <Route path="/triples" element={<Triples />} />
              <Route path="/kg-types" element={<KGTypes />} />
              
              {/* Hierarchical routes */}
              <Route path="/space/:spaceId/graphs" element={<Graphs />} />
              <Route path="/space/:spaceId/graph/:graphId/objects" element={<Navigate to="graphobjects" replace />} />
              <Route path="/space/:spaceId/graph/:graphId/objects/*" element={<ObjectsLayout />}>
                <Route path="graphobjects" element={<GraphObjects />} />
                <Route path="kgentities" element={<KGEntities />} />
                <Route path="kgframes" element={<KGFrames />} />
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
              <Route path="/data/migrate" element={<Data />} />
              <Route path="/data/tracking" element={<Data />} />
              <Route path="/data/checkpoint" element={<Data />} />
              <Route path="/data/import/new" element={<DataImportDetail />} />
              <Route path="/data/import/:importId" element={<DataImportDetail />} />
              <Route path="/data/export/new" element={<DataExportDetail />} />
              <Route path="/data/export/:exportId" element={<DataExportDetail />} />
              <Route path="/data/migrate/new" element={<DataMigrationDetail />} />
              <Route path="/data/migrate/:migrationId" element={<DataMigrationDetail />} />
              <Route path="/data/tracking/new" element={<DataTrackingDetail />} />
              <Route path="/data/tracking/:trackingId" element={<DataTrackingDetail />} />
              <Route path="/data/checkpoint/new" element={<DataCheckpointDetail />} />
              <Route path="/data/checkpoint/:checkpointId" element={<DataCheckpointDetail />} />
              
              {/* Detail routes */}
              <Route path="/space/:id" element={<SpaceDetail />} />
              <Route path="/space/:spaceId/graph/:graphId" element={<GraphDetail />} />
              <Route path="/space/:spaceId/graph/:graphId/analysis" element={<GraphAnalysis />} />
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
          
          {/* Redirect any other routes to home */}
          <Route path="*" element={<Navigate to="/" />} />
            </Routes>
          </ChangeNotificationProvider>
        </BrowserRouter>
      </WebSocketProvider>
    </AuthProvider>
  );
}
