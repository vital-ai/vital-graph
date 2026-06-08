import React, { useState, useEffect, useCallback } from 'react';
import { Card, Spinner, Button, Alert, Badge, Select } from 'flowbite-react';
import { HiRefresh, HiClock } from 'react-icons/hi';
import Chart from 'react-apexcharts';
import { apiService } from '../services/ApiService';

interface EndpointSeries {
  counts: number[];
  avg_ms: number[];
  max_ms: number[];
  errors: number[];
}

interface MetricsData {
  success: boolean;
  space_id: string;
  range: string;
  granularity: string;
  timestamps: string[];
  series: Record<string, EndpointSeries>;
  totals: {
    total_requests: number;
    total_errors: number;
    avg_latency_ms: number;
  };
}

interface SlowQuery {
  ts: number;
  space_id: string;
  endpoint: string;
  ms: number;
  method?: string;
  path?: string;
}

interface Props {
  spaceId: string;
}

const chartColors = [
  '#1C64F2', '#16BDCA', '#9061F9', '#E74694', '#FDBA8C',
  '#31C48D', '#F98080', '#6875F5', '#84E1BC', '#FACA15',
];

const StatCard: React.FC<{ label: string; value: string | number; color?: string }> = ({ label, value, color }) => (
  <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-4 text-center">
    <div className={`text-2xl font-bold ${color || 'text-gray-900 dark:text-white'}`}>
      {typeof value === 'number' ? value.toLocaleString() : value}
    </div>
    <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">{label}</div>
  </div>
);

const SpaceMetrics: React.FC<Props> = ({ spaceId }) => {
  const [metrics, setMetrics] = useState<MetricsData | null>(null);
  const [slowQueries, setSlowQueries] = useState<SlowQuery[]>([]);
  const [loading, setLoading] = useState(true);
  const [timeRange, setTimeRange] = useState<string>('realtime');
  const [error, setError] = useState<string | null>(null);

  const fetchMetrics = useCallback(async () => {
    try {
      setLoading(true);
      const [metricsResp, slowResp] = await Promise.all([
        apiService.getSpaceMetrics(spaceId, timeRange),
        apiService.getSpaceSlowQueries(spaceId, 20),
      ]);

      if (metricsResp.success) {
        setMetrics(metricsResp);
        setError(null);
      } else {
        setError(metricsResp.message || 'Failed to load metrics');
      }

      if (slowResp.success) {
        setSlowQueries(slowResp.slow_queries || []);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load metrics');
    } finally {
      setLoading(false);
    }
  }, [spaceId, timeRange]);

  useEffect(() => {
    fetchMetrics();
  }, [fetchMetrics]);

  // Auto-refresh every 30s for realtime view
  useEffect(() => {
    if (timeRange !== 'realtime') return;
    const interval = setInterval(fetchMetrics, 30000);
    return () => clearInterval(interval);
  }, [timeRange, fetchMetrics]);

  if (loading && !metrics) {
    return (
      <div className="flex items-center justify-center py-12">
        <Spinner size="lg" />
        <span className="ml-3 text-gray-500">Loading metrics...</span>
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

  if (!metrics || Object.keys(metrics.series).length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500 dark:text-gray-400 mb-4">
          No query metrics recorded yet. Metrics will appear after API requests are made to this space.
        </p>
        <Button onClick={fetchMetrics} size="sm" color="gray">
          <HiRefresh className="mr-2 h-4 w-4" />Check Again
        </Button>
      </div>
    );
  }

  const endpoints = Object.keys(metrics.series);
  const timestamps = metrics.timestamps;

  // Build time-series chart data
  const requestsChartOptions: ApexCharts.ApexOptions = {
    chart: {
      type: 'area',
      fontFamily: 'Inter, sans-serif',
      toolbar: { show: false },
      stacked: true,
    },
    stroke: { width: 2, curve: 'smooth' },
    fill: { type: 'gradient', gradient: { opacityFrom: 0.4, opacityTo: 0.05 } },
    xaxis: {
      categories: timestamps.map(ts => {
        const d = new Date(typeof ts === 'number' ? ts * 1000 : ts);
        return metrics.granularity === 'minute'
          ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
          : d.toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit' });
      }),
      labels: { show: true, rotate: -45, style: { fontSize: '10px' } },
      tickAmount: 12,
    },
    yaxis: { title: { text: 'Requests' }, labels: { style: { fontSize: '11px' } } },
    colors: chartColors.slice(0, endpoints.length),
    legend: { position: 'top', fontSize: '11px' },
    tooltip: { shared: true, intersect: false },
    grid: { borderColor: '#E5E7EB', strokeDashArray: 4 },
  };

  const requestsSeries = endpoints.map(ep => ({
    name: ep,
    data: metrics.series[ep].counts,
  }));

  // Latency chart (avg + max as dual-axis)
  const latencyChartOptions: ApexCharts.ApexOptions = {
    chart: {
      type: 'line',
      fontFamily: 'Inter, sans-serif',
      toolbar: { show: false },
    },
    stroke: { width: [2, 1], curve: 'smooth', dashArray: [0, 4] },
    xaxis: {
      categories: timestamps.map(ts => {
        const d = new Date(typeof ts === 'number' ? ts * 1000 : ts);
        return metrics.granularity === 'minute'
          ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
          : d.toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit' });
      }),
      labels: { show: true, rotate: -45, style: { fontSize: '10px' } },
      tickAmount: 12,
    },
    yaxis: { title: { text: 'Latency (ms)' }, labels: { style: { fontSize: '11px' } } },
    colors: ['#1C64F2', '#F98080'],
    legend: { position: 'top', fontSize: '11px' },
    tooltip: { shared: true, intersect: false },
    grid: { borderColor: '#E5E7EB', strokeDashArray: 4 },
  };

  // Aggregate latency across all endpoints per timestamp
  const avgLatencyPerTs = timestamps.map((_, i) => {
    let totalSum = 0, totalCount = 0;
    for (const ep of endpoints) {
      const avg = metrics.series[ep].avg_ms[i];
      const count = metrics.series[ep].counts[i];
      if (count > 0) {
        totalSum += avg * count;
        totalCount += count;
      }
    }
    return totalCount > 0 ? Math.round(totalSum / totalCount) : 0;
  });

  const maxLatencyPerTs = timestamps.map((_, i) => {
    let maxVal = 0;
    for (const ep of endpoints) {
      maxVal = Math.max(maxVal, metrics.series[ep].max_ms[i]);
    }
    return maxVal;
  });

  const latencySeries = [
    { name: 'Avg Latency', data: avgLatencyPerTs },
    { name: 'Max Latency', data: maxLatencyPerTs },
  ];

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Select
            value={timeRange}
            onChange={e => setTimeRange(e.target.value)}
            sizing="sm"
          >
            <option value="realtime">Last 60 min</option>
            <option value="24h">Last 24h</option>
            <option value="7d">Last 7 days</option>
            <option value="30d">Last 30 days</option>
          </Select>
          {timeRange === 'realtime' && (
            <Badge color="info" className="text-xs">
              <HiClock className="inline h-3 w-3 mr-1" />Auto-refreshing
            </Badge>
          )}
        </div>
        <Button size="sm" color="gray" onClick={fetchMetrics} disabled={loading}>
          {loading ? <Spinner size="sm" /> : <HiRefresh className="h-4 w-4" />}
          <span className="ml-1">Refresh</span>
        </Button>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Total Requests" value={metrics.totals.total_requests} />
        <StatCard
          label="Errors"
          value={metrics.totals.total_errors}
          color={metrics.totals.total_errors > 0 ? 'text-red-600' : undefined}
        />
        <StatCard label="Avg Latency" value={`${metrics.totals.avg_latency_ms}ms`} />
        <StatCard label="Endpoints" value={endpoints.length} />
      </div>

      {/* Requests Over Time */}
      <Card>
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
          Requests Over Time
        </h3>
        <Chart
          type="area"
          height={280}
          options={requestsChartOptions}
          series={requestsSeries}
        />
      </Card>

      {/* Latency Over Time */}
      <Card>
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
          Latency Over Time
        </h3>
        <Chart
          type="line"
          height={250}
          options={latencyChartOptions}
          series={latencySeries}
        />
      </Card>

      {/* Slow Queries */}
      {slowQueries.length > 0 && (
        <Card>
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
            Recent Slow Queries ({'>'}500ms)
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left text-gray-500 dark:text-gray-400">
              <thead className="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400">
                <tr>
                  <th className="px-4 py-2">Time</th>
                  <th className="px-4 py-2">Endpoint</th>
                  <th className="px-4 py-2">Duration</th>
                  <th className="px-4 py-2">Path</th>
                </tr>
              </thead>
              <tbody>
                {slowQueries.map((sq, idx) => (
                  <tr key={idx} className="bg-white border-b dark:bg-gray-800 dark:border-gray-700">
                    <td className="px-4 py-2 text-xs whitespace-nowrap">
                      {new Date(sq.ts * 1000).toLocaleTimeString()}
                    </td>
                    <td className="px-4 py-2">
                      <Badge color="gray" size="sm">{sq.endpoint}</Badge>
                    </td>
                    <td className="px-4 py-2">
                      <span className={sq.ms > 1000 ? 'text-red-600 font-semibold' : 'text-yellow-600'}>
                        {Math.round(sq.ms)}ms
                      </span>
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-500 truncate max-w-[200px]">
                      {sq.path || '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
};

export default SpaceMetrics;
