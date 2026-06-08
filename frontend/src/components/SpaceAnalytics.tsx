import React, { useState, useEffect, useCallback } from 'react';
import { Card, Spinner, Button, Alert, Badge, Select } from 'flowbite-react';
import { HiRefresh, HiClock, HiFilter } from 'react-icons/hi';
import Chart from 'react-apexcharts';
import { apiService } from '../services/ApiService';

interface TypeCount {
  type_uri: string;
  type_name: string;
  count: number;
}

interface ConnectedEntity {
  entity_uri: string;
  entity_name: string | null;
  edge_count: number;
}

interface PredicateCount {
  predicate_uri: string;
  short_name: string;
  count: number;
}

interface EntityAnalytics {
  total_count: number;
  type_distribution: TypeCount[];
  with_frames_count: number;
  orphan_count: number;
  avg_frames_per_entity: number;
}

interface FrameAnalytics {
  total_count: number;
  type_distribution: TypeCount[];
  total_slot_count: number;
  slot_type_distribution: TypeCount[];
  avg_slots_per_frame: number;
  without_slots_count: number;
}

interface RelationAnalytics {
  total_edge_count: number;
  edge_type_distribution: TypeCount[];
  inter_entity_relation_count: number;
  entity_frame_edge_count: number;
  frame_slot_edge_count: number;
  most_connected_entities: ConnectedEntity[];
}

interface PropertyAnalytics {
  distinct_predicate_count: number;
  top_predicates: PredicateCount[];
  literal_type_distribution: TypeCount[];
}

interface AnalyticsData {
  space_id: string;
  computed_at: string | null;
  computation_time_ms: number | null;
  stale: boolean;
  entity_analytics: EntityAnalytics;
  frame_analytics: FrameAnalytics;
  relation_analytics: RelationAnalytics;
  property_analytics: PropertyAnalytics;
}

interface GraphInfo {
  graph_uri: string;
  graph_name?: string;
}

interface Props {
  spaceId: string;
}

const chartColors = [
  '#1C64F2', '#16BDCA', '#9061F9', '#E74694', '#FDBA8C',
  '#31C48D', '#F98080', '#6875F5', '#84E1BC', '#FACA15',
];

const horizontalBarOptions = (categories: string[]): ApexCharts.ApexOptions => ({
  chart: {
    type: 'bar',
    fontFamily: 'Inter, sans-serif',
    toolbar: { show: false },
    animations: { enabled: true, speed: 600 },
  },
  plotOptions: {
    bar: { horizontal: true, borderRadius: 4, barHeight: '70%' },
  },
  dataLabels: {
    enabled: true,
    formatter: (val: number) => val >= 1000 ? `${(val / 1000).toFixed(1)}k` : String(val),
    style: { fontSize: '11px', colors: ['#6B7280'] },
    offsetX: 5,
  },
  xaxis: {
    categories,
    labels: {
      style: { fontSize: '11px', colors: '#6B7280' },
      formatter: (val: string) => {
        const n = Number(val);
        return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : val;
      },
    },
  },
  yaxis: {
    labels: {
      style: { fontSize: '11px', colors: '#6B7280' },
      maxWidth: 200,
      formatter: (val: number) => {
        const s = String(val);
        return s.length > 24 ? s.slice(0, 22) + '...' : s;
      },
    },
  },
  grid: { borderColor: '#E5E7EB', strokeDashArray: 4 },
  colors: [chartColors[0]],
  fill: {
    type: 'gradient',
    gradient: { shade: 'light', type: 'horizontal', opacityFrom: 0.85, opacityTo: 1, stops: [0, 100] },
  },
  tooltip: {
    y: { formatter: (val: number) => val.toLocaleString() },
  },
});

const donutOptions = (labels: string[]): ApexCharts.ApexOptions => ({
  chart: {
    type: 'donut',
    fontFamily: 'Inter, sans-serif',
    animations: { enabled: true, animateGradually: { enabled: true, delay: 100 } },
  },
  labels,
  colors: chartColors.slice(0, labels.length),
  legend: {
    position: 'bottom',
    fontSize: '12px',
    labels: { colors: '#6B7280' },
  },
  plotOptions: {
    pie: {
      donut: {
        size: '55%',
        labels: {
          show: true,
          total: {
            show: true,
            label: 'Total',
            formatter: (w: { globals: { seriesTotals: number[] } }) =>
              w.globals.seriesTotals.reduce((a: number, b: number) => a + b, 0).toLocaleString(),
          },
        },
      },
    },
  },
  dataLabels: {
    enabled: true,
    formatter: ((_val: number, opts?: { seriesIndex: number; w: { config: { series: number[] } } }) => {
      if (!opts) return String(_val);
      return opts.w.config.series[opts.seriesIndex].toLocaleString();
    }) as (val: string | number | number[], opts?: unknown) => string | number,
  },
  tooltip: {
    y: { formatter: (val: number) => val.toLocaleString() },
  },
  stroke: { width: 2, colors: ['#fff'] },
  responsive: [{ breakpoint: 480, options: { chart: { width: 280 }, legend: { position: 'bottom' } } }],
});

const StatCard: React.FC<{ label: string; value: string | number }> = ({ label, value }) => (
  <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-4 text-center">
    <div className="text-2xl font-bold text-gray-900 dark:text-white">{typeof value === 'number' ? value.toLocaleString() : value}</div>
    <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">{label}</div>
  </div>
);

const SpaceAnalytics: React.FC<Props> = ({ spaceId }) => {
  const [analytics, setAnalytics] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [graphs, setGraphs] = useState<GraphInfo[]>([]);
  const [selectedGraph, setSelectedGraph] = useState<string>('');

  // Fetch available graphs from space info
  useEffect(() => {
    const loadGraphs = async () => {
      try {
        const info = await apiService.getSpaceInfo(spaceId);
        const stats = info?.statistics;
        if (stats?.graphs) {
          setGraphs(stats.graphs);
        }
      } catch {
        // Graph list is optional, ignore errors
      }
    };
    loadGraphs();
  }, [spaceId]);

  const fetchAnalytics = useCallback(async (refresh = false) => {
    try {
      if (refresh) setRefreshing(true);
      else setLoading(true);

      const graphUri = selectedGraph || undefined;
      const response = await apiService.getSpaceAnalytics(spaceId, refresh, graphUri);
      if (response.success && response.analytics) {
        setAnalytics(response.analytics);
        setError(null);
      } else if (response.success && !response.analytics) {
        setAnalytics(null);
        setError(null);
      } else {
        setError(response.message || 'Failed to load analytics');
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load analytics');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [spaceId, selectedGraph]);

  useEffect(() => {
    fetchAnalytics();
  }, [fetchAnalytics]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Spinner size="lg" />
        <span className="ml-3 text-gray-500">Loading analytics...</span>
      </div>
    );
  }

  if (error) {
    return (
      <Alert color="failure" className="mb-4">
        {error}
      </Alert>
    );
  }

  if (!analytics) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500 dark:text-gray-400 mb-4">
          No analytics have been computed for this space yet.
        </p>
        <Button onClick={() => fetchAnalytics(true)} disabled={refreshing}>
          {refreshing ? <><Spinner size="sm" className="mr-2" />Computing...</> : <><HiRefresh className="mr-2 h-4 w-4" />Compute Now</>}
        </Button>
      </div>
    );
  }

  const { entity_analytics, frame_analytics, relation_analytics, property_analytics } = analytics;

  return (
    <div className="space-y-6">
      {/* Header with metadata and graph filter */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3 flex-wrap">
          {analytics.stale && (
            <Badge color="warning">Stale</Badge>
          )}
          {selectedGraph && (
            <Badge color="info">Filtered: {graphs.find(g => g.graph_uri === selectedGraph)?.graph_name || selectedGraph.split('/').pop()}</Badge>
          )}
          {analytics.computed_at && (
            <span className="text-xs text-gray-500 dark:text-gray-400 flex items-center gap-1">
              <HiClock className="h-3 w-3" />
              {new Date(analytics.computed_at).toLocaleString()}
              {analytics.computation_time_ms != null && ` (${analytics.computation_time_ms}ms)`}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {graphs.length > 0 && (
            <div className="flex items-center gap-1">
              <HiFilter className="h-4 w-4 text-gray-400" />
              <Select
                sizing="sm"
                value={selectedGraph}
                onChange={(e) => setSelectedGraph(e.target.value)}
              >
                <option value="">All Graphs</option>
                {graphs.map((g) => (
                  <option key={g.graph_uri} value={g.graph_uri}>
                    {g.graph_name || g.graph_uri.split('/').pop()}
                  </option>
                ))}
              </Select>
            </div>
          )}
          <Button size="sm" color="gray" onClick={() => fetchAnalytics(true)} disabled={refreshing}>
            {refreshing ? <Spinner size="sm" /> : <HiRefresh className="h-4 w-4" />}
            <span className="ml-1">Refresh</span>
          </Button>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Entities" value={entity_analytics.total_count} />
        <StatCard label="Frames" value={frame_analytics.total_count} />
        <StatCard label="Edges" value={relation_analytics.total_edge_count} />
        <StatCard label="Predicates" value={property_analytics.distinct_predicate_count} />
      </div>

      {/* Entity Analytics */}
      <Card>
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Entity Analytics</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          <StatCard label="With Frames" value={entity_analytics.with_frames_count} />
          <StatCard label="Orphan (no frames)" value={entity_analytics.orphan_count} />
          <StatCard label="Avg Frames/Entity" value={entity_analytics.avg_frames_per_entity} />
        </div>
        {entity_analytics.type_distribution.length > 0 && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div>
              <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Type Distribution</h4>
              <Chart
                type="bar"
                height={Math.max(200, entity_analytics.type_distribution.length * 40)}
                options={horizontalBarOptions(entity_analytics.type_distribution.map(t => t.type_name))}
                series={[{ name: 'Count', data: entity_analytics.type_distribution.map(t => t.count) }]}
              />
            </div>
            {entity_analytics.type_distribution.length <= 8 && (
              <div>
                <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Proportions</h4>
                <Chart
                  type="donut"
                  height={280}
                  options={donutOptions(entity_analytics.type_distribution.map(t => t.type_name))}
                  series={entity_analytics.type_distribution.map(t => t.count)}
                />
              </div>
            )}
          </div>
        )}
      </Card>

      {/* Frame & Slot Analytics */}
      <Card>
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Frame & Slot Analytics</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          <StatCard label="Total Slots" value={frame_analytics.total_slot_count} />
          <StatCard label="Avg Slots/Frame" value={frame_analytics.avg_slots_per_frame} />
          <StatCard label="Frames w/o Slots" value={frame_analytics.without_slots_count} />
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {frame_analytics.type_distribution.length > 0 && (
            <div>
              <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Frame Types</h4>
              <Chart
                type="bar"
                height={Math.max(200, frame_analytics.type_distribution.length * 40)}
                options={horizontalBarOptions(frame_analytics.type_distribution.map(t => t.type_name))}
                series={[{ name: 'Count', data: frame_analytics.type_distribution.map(t => t.count) }]}
              />
            </div>
          )}
          {frame_analytics.slot_type_distribution.length > 0 && (
            <div>
              <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Slot Types</h4>
              <Chart
                type="bar"
                height={Math.max(200, frame_analytics.slot_type_distribution.length * 40)}
                options={horizontalBarOptions(frame_analytics.slot_type_distribution.map(t => t.type_name))}
                series={[{ name: 'Count', data: frame_analytics.slot_type_distribution.map(t => t.count) }]}
              />
            </div>
          )}
        </div>
      </Card>

      {/* Relation Analytics */}
      <Card>
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Relation Analytics</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          <StatCard label="Entity Relations" value={relation_analytics.inter_entity_relation_count} />
          <StatCard label="Entity-Frame Edges" value={relation_analytics.entity_frame_edge_count} />
          <StatCard label="Frame-Slot Edges" value={relation_analytics.frame_slot_edge_count} />
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {relation_analytics.edge_type_distribution.length > 0 && (
            <div>
              <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Edge Type Distribution</h4>
              {relation_analytics.edge_type_distribution.length <= 8 ? (
                <Chart
                  type="donut"
                  height={280}
                  options={donutOptions(relation_analytics.edge_type_distribution.map(t => t.type_name))}
                  series={relation_analytics.edge_type_distribution.map(t => t.count)}
                />
              ) : (
                <Chart
                  type="bar"
                  height={Math.max(200, relation_analytics.edge_type_distribution.length * 40)}
                  options={horizontalBarOptions(relation_analytics.edge_type_distribution.map(t => t.type_name))}
                  series={[{ name: 'Count', data: relation_analytics.edge_type_distribution.map(t => t.count) }]}
                />
              )}
            </div>
          )}
          {relation_analytics.most_connected_entities.length > 0 && (
            <div>
              <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Most Connected Entities</h4>
              <Chart
                type="bar"
                height={Math.max(200, relation_analytics.most_connected_entities.length * 40)}
                options={horizontalBarOptions(relation_analytics.most_connected_entities.map(e => e.entity_name || e.entity_uri))}
                series={[{ name: 'Edges', data: relation_analytics.most_connected_entities.map(e => e.edge_count) }]}
              />
            </div>
          )}
        </div>
      </Card>

      {/* Property Analytics */}
      <Card>
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Property Analytics</h3>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {property_analytics.top_predicates.length > 0 && (
            <div>
              <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Top Predicates</h4>
              <Chart
                type="bar"
                height={Math.max(250, property_analytics.top_predicates.length * 32)}
                options={horizontalBarOptions(property_analytics.top_predicates.map(p => p.short_name))}
                series={[{ name: 'Usage', data: property_analytics.top_predicates.map(p => p.count) }]}
              />
            </div>
          )}
          {property_analytics.literal_type_distribution.length > 0 && (
            <div>
              <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Literal Datatypes</h4>
              <Chart
                type="donut"
                height={280}
                options={donutOptions(property_analytics.literal_type_distribution.map(t => t.type_name))}
                series={property_analytics.literal_type_distribution.map(t => t.count)}
              />
            </div>
          )}
        </div>
      </Card>
    </div>
  );
};

export default SpaceAnalytics;
