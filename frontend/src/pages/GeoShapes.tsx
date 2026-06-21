import React, { useState, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import {
  Alert,
  Button,
  Label,
  Select,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeadCell,
  TableRow,
  TextInput,
  Pagination,
  Breadcrumb,
  BreadcrumbItem,
} from 'flowbite-react';
import { HiLocationMarker, HiSearch, HiViewList, HiMap, HiGlobe, HiHome } from 'react-icons/hi';
import { MapContainer, TileLayer, Marker, Popup, Circle, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { APIProvider, Map as GoogleMap, AdvancedMarker, InfoWindow } from '@vis.gl/react-google-maps';
import { vectorGeoService } from '../services/VectorGeoService';
import { apiService } from '../services/ApiService';
import type { GeoPoint, GeoPointsQuery } from '../types/vectorGeo';
import { type SpaceInfo } from '../types/api';

import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png';
import markerIcon from 'leaflet/dist/images/marker-icon.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';

delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
});

function MapRecenter({ points }: { points: GeoPoint[] }) {
  const map = useMap();
  useEffect(() => {
    if (points.length === 0) return;
    const bounds = L.latLngBounds(points.map((p) => [p.latitude, p.longitude]));
    map.fitBounds(bounds, { padding: [30, 30], maxZoom: 14 });
  }, [points, map]);
  return null;
}

type ViewMode = 'map' | 'google' | 'table';

const GOOGLE_MAPS_API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY || '';

const GeoShapes: React.FC = () => {
  const { spaceId } = useParams<{ spaceId?: string }>();

  const [spaces, setSpaces] = useState<SpaceInfo[]>([]);
  const [selectedSpace, setSelectedSpace] = useState<string>(spaceId || '');
  const [points, setPoints] = useState<GeoPoint[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [spacesLoading, setSpacesLoading] = useState(true);
  const [viewMode, setViewMode] = useState<ViewMode>('table');
  const [selectedMarker, setSelectedMarker] = useState<GeoPoint | null>(null);

  // Query params
  const [lat, setLat] = useState('');
  const [lon, setLon] = useState('');
  const [radius, setRadius] = useState('5000');
  const [page, setPage] = useState(1);
  const pageSize = 50;

  useEffect(() => {
    const loadSpaces = async () => {
      try {
        const data = await apiService.getSpaces();
        setSpaces(data);
        if (!selectedSpace && data.length > 0) {
          setSelectedSpace(data[0].space);
        }
      } catch {
        setError('Failed to load spaces');
      } finally {
        setSpacesLoading(false);
      }
    };
    loadSpaces();
  }, []);

  const loadPoints = useCallback(async () => {
    if (!selectedSpace) return;
    setLoading(true);
    setError(null);
    try {
      const query: GeoPointsQuery = {
        limit: pageSize,
        offset: (page - 1) * pageSize,
      };
      if (lat && lon) {
        query.near_lat = parseFloat(lat);
        query.near_lon = parseFloat(lon);
        query.radius_km = (parseFloat(radius) || 5000) / 1000;
      }
      const response = await vectorGeoService.getGeoPoints(selectedSpace, query);
      setPoints(response.points || []);
      setTotalCount(response.total_count || 0);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load geo data');
      setPoints([]);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace, lat, lon, radius, page]);

  useEffect(() => {
    loadPoints();
  }, [loadPoints]);

  const totalPages = Math.ceil(totalCount / pageSize);

  return (
    <div>
      <Breadcrumb className="mb-6">
        <BreadcrumbItem href="/" icon={HiHome}>Home</BreadcrumbItem>
        <BreadcrumbItem>Geo Shapes</BreadcrumbItem>
      </Breadcrumb>

      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          <HiGlobe className="inline mr-2 h-6 w-6" />
          Geo Shapes
        </h1>
        <div className="flex gap-2">
          <Button size="sm" color={viewMode === 'table' ? 'blue' : 'gray'} onClick={() => setViewMode('table')}>
            <HiViewList className="mr-1 h-4 w-4" /> Table
          </Button>
          <Button size="sm" color={viewMode === 'map' ? 'blue' : 'gray'} onClick={() => setViewMode('map')}>
            <HiMap className="mr-1 h-4 w-4" /> Map
          </Button>
          {GOOGLE_MAPS_API_KEY && (
            <Button size="sm" color={viewMode === 'google' ? 'blue' : 'gray'} onClick={() => setViewMode('google')}>
              <HiLocationMarker className="mr-1 h-4 w-4" /> Google
            </Button>
          )}
        </div>
      </div>

      {error && (
        <Alert color="failure" className="mb-4" onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Filters */}
      <div className="flex gap-4 mb-4 items-end flex-wrap">
        <div className="w-48">
          <Label htmlFor="space">Space</Label>
          {spacesLoading ? <Spinner size="sm" /> : (
            <Select id="space" value={selectedSpace} onChange={(e) => { setSelectedSpace(e.target.value); setPage(1); }}>
              {spaces.map((s) => (
                <option key={s.space} value={s.space}>{s.space}</option>
              ))}
            </Select>
          )}
        </div>
        <div className="w-28">
          <Label htmlFor="lat">Latitude</Label>
          <TextInput id="lat" type="number" step="0.0001" value={lat} onChange={(e) => setLat(e.target.value)} placeholder="optional" />
        </div>
        <div className="w-28">
          <Label htmlFor="lon">Longitude</Label>
          <TextInput id="lon" type="number" step="0.0001" value={lon} onChange={(e) => setLon(e.target.value)} placeholder="optional" />
        </div>
        <div className="w-28">
          <Label htmlFor="radius">Radius (m)</Label>
          <TextInput id="radius" type="number" value={radius} onChange={(e) => setRadius(e.target.value)} />
        </div>
        <Button size="sm" color="blue" onClick={() => { setPage(1); loadPoints(); }}>
          <HiSearch className="mr-1 h-4 w-4" /> Query
        </Button>
      </div>

      <div className="mb-2 text-sm text-gray-500">
        {totalCount} shapes found
      </div>

      {/* Content */}
      {loading ? (
        <div className="flex justify-center py-12">
          <Spinner size="xl" />
        </div>
      ) : viewMode === 'table' ? (
        <>
          <Table striped>
            <TableHead>
              <TableRow>
                <TableHeadCell>Subject</TableHeadCell>
                <TableHeadCell>Latitude</TableHeadCell>
                <TableHeadCell>Longitude</TableHeadCell>
                <TableHeadCell>Context</TableHeadCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {points.map((p, i) => (
                <TableRow key={i}>
                  <TableCell className="max-w-xs truncate font-mono text-xs" title={p.subject_uri}>
                    {p.subject_uri}
                  </TableCell>
                  <TableCell>{p.latitude.toFixed(6)}</TableCell>
                  <TableCell>{p.longitude.toFixed(6)}</TableCell>
                  <TableCell className="max-w-xs truncate text-xs" title={p.context_uuid}>
                    {p.context_uuid || '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {totalPages > 1 && (
            <div className="flex justify-center mt-4">
              <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
            </div>
          )}
        </>
      ) : viewMode === 'map' ? (
        <div className="h-[500px] rounded-lg overflow-hidden border">
          <MapContainer center={[40.7128, -74.006]} zoom={10} className="h-full w-full">
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            />
            {lat && lon && (
              <Circle center={[parseFloat(lat), parseFloat(lon)]} radius={parseFloat(radius) || 5000} pathOptions={{ color: 'blue', fillOpacity: 0.1 }} />
            )}
            {points.map((p, i) => (
              <Marker key={i} position={[p.latitude, p.longitude]}>
                <Popup>
                  <div className="text-xs">
                    <p className="font-bold truncate max-w-[200px]">{p.subject_uri}</p>
                    <p>{p.latitude.toFixed(6)}, {p.longitude.toFixed(6)}</p>
                  </div>
                </Popup>
              </Marker>
            ))}
            <MapRecenter points={points} />
          </MapContainer>
        </div>
      ) : (
        GOOGLE_MAPS_API_KEY ? (
          <div className="h-[500px] rounded-lg overflow-hidden border">
            <APIProvider apiKey={GOOGLE_MAPS_API_KEY}>
              <GoogleMap
                defaultCenter={{ lat: 40.7128, lng: -74.006 }}
                defaultZoom={10}
                mapId="geo-shapes-map"
                style={{ width: '100%', height: '100%' }}
              >
                {points.map((p, i) => (
                  <AdvancedMarker
                    key={i}
                    position={{ lat: p.latitude, lng: p.longitude }}
                    onClick={() => setSelectedMarker(p)}
                  />
                ))}
                {selectedMarker && (
                  <InfoWindow
                    position={{ lat: selectedMarker.latitude, lng: selectedMarker.longitude }}
                    onCloseClick={() => setSelectedMarker(null)}
                  >
                    <div className="text-xs">
                      <p className="font-bold truncate max-w-[200px]">{selectedMarker.subject_uri}</p>
                      <p>{selectedMarker.latitude.toFixed(6)}, {selectedMarker.longitude.toFixed(6)}</p>
                    </div>
                  </InfoWindow>
                )}
              </GoogleMap>
            </APIProvider>
          </div>
        ) : (
          <Alert color="warning">Google Maps API key not configured.</Alert>
        )
      )}
    </div>
  );
};

export default GeoShapes;
