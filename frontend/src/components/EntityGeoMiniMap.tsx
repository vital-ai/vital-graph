import React, { useState, useEffect } from 'react';
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { HiLocationMarker } from 'react-icons/hi';

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

interface EntityGeoMiniMapProps {
  spaceId: string;
  entityUri: string;
}

interface GeoData {
  latitude: number;
  longitude: number;
}

/**
 * A compact mini-map component that shows the geo location of a KG entity.
 * Fetches the entity's geo coordinates from the backend and renders a small map.
 * Renders nothing if the entity has no geo data.
 */
const EntityGeoMiniMap: React.FC<EntityGeoMiniMapProps> = ({ spaceId, entityUri }) => {
  const [geo, setGeo] = useState<GeoData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!spaceId || !entityUri) {
      setLoading(false);
      return;
    }

    const fetchGeo = async () => {
      try {
        const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
        const token = localStorage.getItem('access_token');
        const params = new URLSearchParams({ space_id: spaceId, subject_uri: entityUri, limit: '1' });
        const response = await fetch(`${baseUrl}/api/geo?${params}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (response.ok) {
          const data = await response.json();
          const points = data.points || [];
          if (points.length > 0) {
            setGeo({ latitude: points[0].latitude, longitude: points[0].longitude });
          }
        }
      } catch {
        // Silently ignore — geo data is optional
      } finally {
        setLoading(false);
      }
    };
    fetchGeo();
  }, [spaceId, entityUri]);

  if (loading || !geo) return null;

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
        <HiLocationMarker className="h-4 w-4 text-blue-500" />
        <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Location</span>
        <span className="text-xs text-gray-500 ml-auto">
          {geo.latitude.toFixed(5)}, {geo.longitude.toFixed(5)}
        </span>
      </div>
      <div style={{ height: '200px' }}>
        <MapContainer
          center={[geo.latitude, geo.longitude]}
          zoom={12}
          style={{ height: '100%', width: '100%' }}
          scrollWheelZoom={false}
          dragging={false}
          zoomControl={false}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <Marker position={[geo.latitude, geo.longitude]}>
            <Popup>{entityUri}</Popup>
          </Marker>
        </MapContainer>
      </div>
    </div>
  );
};

export default EntityGeoMiniMap;
