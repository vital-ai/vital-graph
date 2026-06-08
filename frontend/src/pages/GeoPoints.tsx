import React, { useState, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import {
  Alert,
  Badge,
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
} from 'flowbite-react';
import { HiLocationMarker, HiSearch, HiViewList, HiMap, HiGlobe } from 'react-icons/hi';
import { MapContainer, TileLayer, Marker, Popup, Circle, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { APIProvider, Map as GoogleMap, AdvancedMarker, InfoWindow } from '@vis.gl/react-google-maps';
import { vectorGeoService } from '../services/VectorGeoService';
import { apiService } from '../services/ApiService';
import type { GeoPoint, GeoPointsQuery } from '../types/vectorGeo';
import { type SpaceInfo } from '../types/api';

// Fix default marker icons for leaflet in bundled apps
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png';
import markerIcon from 'leaflet/dist/images/marker-icon.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';

delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
});


// Component to recenter map when points change
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

const GeoPoints: React.FC = () => {
  const { spaceId } = useParams<{ spaceId?: string }>();

  const [spaces, setSpaces] = useState<SpaceInfo[]>([]);
  const [selectedSpace, setSelectedSpace] = useState<string>(spaceId || '');
  const [points, setPoints] = useState<GeoPoint[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [spacesLoading, setSpacesLoading] = useState(true);
  const [viewMode, setViewMode] = useState<ViewMode>('map');

  // Pagination
  const [page, setPage] = useState(1);
  const pageSize = 50;

  // Google Maps InfoWindow
  const [selectedPointIdx, setSelectedPointIdx] = useState<number | null>(null);

  // Spatial filter
  const [nearLat, setNearLat] = useState('');
  const [nearLon, setNearLon] = useState('');
  const [radiusKm, setRadiusKm] = useState('');
  const [spatialActive, setSpatialActive] = useState(false);

  // Load spaces
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

  // Load geo points
  const loadPoints = useCallback(async () => {
    if (!selectedSpace) return;
    setLoading(true);
    setError(null);
    try {
      const query: GeoPointsQuery = {
        limit: pageSize,
        offset: (page - 1) * pageSize,
      };
      if (spatialActive && nearLat && nearLon && radiusKm) {
        query.near_lat = parseFloat(nearLat);
        query.near_lon = parseFloat(nearLon);
        query.radius_km = parseFloat(radiusKm);
      }
      const data = await vectorGeoService.getGeoPoints(selectedSpace, query);
      setPoints(data.points);
      setTotalCount(data.total_count);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load geo points');
      setPoints([]);
      setTotalCount(0);
    } finally {
      setLoading(false);
    }
  }, [selectedSpace, page, spatialActive, nearLat, nearLon, radiusKm]);

  useEffect(() => {
    loadPoints();
  }, [loadPoints]);

  const handleSpatialSearch = () => {
    if (nearLat && nearLon && radiusKm) {
      setSpatialActive(true);
      setPage(1);
    }
  };

  const handleClearSpatial = () => {
    setSpatialActive(false);
    setNearLat('');
    setNearLon('');
    setRadiusKm('');
    setPage(1);
  };

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          <HiLocationMarker className="inline mr-2 h-6 w-6" />
          Geo Points
        </h1>
        <div className="flex gap-2">
          <Button
            size="sm"
            color={viewMode === 'map' ? 'blue' : 'gray'}
            onClick={() => setViewMode('map')}
          >
            <HiMap className="mr-1 h-4 w-4" />
            OSM
          </Button>
          {GOOGLE_MAPS_API_KEY && (
            <Button
              size="sm"
              color={viewMode === 'google' ? 'blue' : 'gray'}
              onClick={() => setViewMode('google')}
            >
              <HiGlobe className="mr-1 h-4 w-4" />
              Google
            </Button>
          )}
          <Button
            size="sm"
            color={viewMode === 'table' ? 'blue' : 'gray'}
            onClick={() => setViewMode('table')}
          >
            <HiViewList className="mr-1 h-4 w-4" />
            Table
          </Button>
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap gap-4 mb-4 items-end">
        {!spaceId && (
          <div className="min-w-48">
            <Label htmlFor="geo-space">Space</Label>
            {spacesLoading ? (
              <Spinner size="sm" />
            ) : (
              <Select id="geo-space" value={selectedSpace} onChange={(e) => { setSelectedSpace(e.target.value); setPage(1); }}>
                <option value="">Select...</option>
                {spaces.map((s) => (
                  <option key={s.space} value={s.space}>
                    {s.space_name || s.space}
                  </option>
                ))}
              </Select>
            )}
          </div>
        )}
        <div className="w-28">
          <Label htmlFor="geo-lat">Latitude</Label>
          <TextInput
            id="geo-lat"
            type="number"
            step="any"
            placeholder="40.71"
            value={nearLat}
            onChange={(e) => setNearLat(e.target.value)}
            sizing="sm"
          />
        </div>
        <div className="w-28">
          <Label htmlFor="geo-lon">Longitude</Label>
          <TextInput
            id="geo-lon"
            type="number"
            step="any"
            placeholder="-74.00"
            value={nearLon}
            onChange={(e) => setNearLon(e.target.value)}
            sizing="sm"
          />
        </div>
        <div className="w-28">
          <Label htmlFor="geo-radius">Radius (km)</Label>
          <TextInput
            id="geo-radius"
            type="number"
            step="any"
            placeholder="50"
            value={radiusKm}
            onChange={(e) => setRadiusKm(e.target.value)}
            sizing="sm"
          />
        </div>
        <Button size="sm" onClick={handleSpatialSearch} disabled={!nearLat || !nearLon || !radiusKm}>
          <HiSearch className="mr-1 h-4 w-4" />
          Search
        </Button>
        {spatialActive && (
          <Button size="sm" color="gray" onClick={handleClearSpatial}>
            Clear
          </Button>
        )}
      </div>

      {/* Status */}
      {error && (
        <Alert color="failure" className="mb-4" onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}

      {spatialActive && (
        <div className="mb-4">
          <Badge color="info">
            Spatial filter: within {radiusKm}km of ({nearLat}, {nearLon}) — {totalCount} result{totalCount !== 1 ? 's' : ''}
          </Badge>
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="flex justify-center py-12">
          <Spinner size="xl" />
        </div>
      ) : points.length === 0 ? (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">
          <HiLocationMarker className="mx-auto h-12 w-12 mb-3 text-gray-300" />
          <p className="text-lg mb-1">No geo points found</p>
          <p className="text-sm">
            {selectedSpace
              ? 'Entities in this space have no geo data, or try adjusting your spatial filter.'
              : 'Select a space to view geo points.'}
          </p>
        </div>
      ) : viewMode === 'map' ? (
        /* Map View */
        <div className="rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700" style={{ height: '550px' }}>
          <MapContainer
            center={[points[0]?.latitude || 0, points[0]?.longitude || 0]}
            zoom={4}
            style={{ height: '100%', width: '100%' }}
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <MapRecenter points={points} />

            {/* Radius circle when spatial filter is active */}
            {spatialActive && nearLat && nearLon && radiusKm && (
              <Circle
                center={[parseFloat(nearLat), parseFloat(nearLon)]}
                radius={parseFloat(radiusKm) * 1000}
                pathOptions={{ color: '#3b82f6', fillColor: '#3b82f6', fillOpacity: 0.1 }}
              />
            )}

            {/* Point markers */}
            {points.map((point, idx) => (
              <Marker key={`${point.subject_uuid}-${idx}`} position={[point.latitude, point.longitude]}>
                <Popup>
                  <div className="text-sm">
                    <div className="font-medium mb-1 max-w-64 truncate">{point.subject_uri}</div>
                    <div className="text-gray-600">
                      {point.latitude.toFixed(6)}, {point.longitude.toFixed(6)}
                    </div>
                    {point.distance_m !== null && (
                      <div className="text-blue-600 mt-1">
                        {point.distance_m < 1000
                          ? `${Math.round(point.distance_m)}m away`
                          : `${(point.distance_m / 1000).toFixed(1)}km away`}
                      </div>
                    )}
                  </div>
                </Popup>
              </Marker>
            ))}
          </MapContainer>
        </div>
      ) : viewMode === 'google' ? (
        /* Google Maps View */
        <div className="rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700" style={{ height: '550px' }}>
          <APIProvider apiKey={GOOGLE_MAPS_API_KEY}>
            <GoogleMap
              defaultCenter={{ lat: points[0]?.latitude || 0, lng: points[0]?.longitude || 0 }}
              defaultZoom={4}
              mapId="geo-points-map"
              style={{ width: '100%', height: '100%' }}
            >
              {points.map((point, idx) => (
                <AdvancedMarker
                  key={`${point.subject_uuid}-${idx}`}
                  position={{ lat: point.latitude, lng: point.longitude }}
                  onClick={() => setSelectedPointIdx(idx)}
                />
              ))}
              {selectedPointIdx !== null && points[selectedPointIdx] && (
                <InfoWindow
                  position={{
                    lat: points[selectedPointIdx].latitude,
                    lng: points[selectedPointIdx].longitude,
                  }}
                  onCloseClick={() => setSelectedPointIdx(null)}
                >
                  <div className="text-sm">
                    <div className="font-medium mb-1 max-w-64 truncate">
                      {points[selectedPointIdx].subject_uri}
                    </div>
                    <div className="text-gray-600">
                      {points[selectedPointIdx].latitude.toFixed(6)}, {points[selectedPointIdx].longitude.toFixed(6)}
                    </div>
                    {points[selectedPointIdx].distance_m !== null && (
                      <div className="text-blue-600 mt-1">
                        {points[selectedPointIdx].distance_m! < 1000
                          ? `${Math.round(points[selectedPointIdx].distance_m!)}m away`
                          : `${(points[selectedPointIdx].distance_m! / 1000).toFixed(1)}km away`}
                      </div>
                    )}
                  </div>
                </InfoWindow>
              )}
            </GoogleMap>
          </APIProvider>
        </div>
      ) : (
        /* Table View */
        <div className="overflow-x-auto">
          <Table hoverable>
            <TableHead>
              <TableHeadCell>Entity URI</TableHeadCell>
              <TableHeadCell>Latitude</TableHeadCell>
              <TableHeadCell>Longitude</TableHeadCell>
              {spatialActive && <TableHeadCell>Distance</TableHeadCell>}
              <TableHeadCell>Updated</TableHeadCell>
            </TableHead>
            <TableBody className="divide-y">
              {points.map((point, idx) => (
                <TableRow key={`${point.subject_uuid}-${idx}`} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                  <TableCell className="text-sm max-w-80 truncate font-medium text-gray-900 dark:text-white">
                    {point.subject_uri}
                  </TableCell>
                  <TableCell className="font-mono text-sm">{point.latitude.toFixed(6)}</TableCell>
                  <TableCell className="font-mono text-sm">{point.longitude.toFixed(6)}</TableCell>
                  {spatialActive && (
                    <TableCell className="text-sm">
                      {point.distance_m !== null
                        ? point.distance_m < 1000
                          ? `${Math.round(point.distance_m)}m`
                          : `${(point.distance_m / 1000).toFixed(1)}km`
                        : '—'}
                    </TableCell>
                  )}
                  <TableCell className="text-sm text-gray-500">
                    {point.updated_time ? new Date(point.updated_time).toLocaleDateString() : '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex justify-center mt-4">
          <Pagination
            currentPage={page}
            totalPages={totalPages}
            onPageChange={setPage}
            showIcons
          />
        </div>
      )}

      {/* Summary */}
      {!loading && points.length > 0 && (
        <div className="mt-3 text-sm text-gray-500 text-center">
          Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, totalCount)} of {totalCount} points
        </div>
      )}
    </div>
  );
};

export default GeoPoints;
