from functools import wraps
from prometheus_client import Gauge, Counter, REGISTRY
from prometheus_client.exposition import start_http_server
from time import time
from datetime import datetime
import json
import asyncio
import bittensor as bt

class PrometheusMetrics:
    def __init__(self, config=None, debug_file='metrics_debug.log'):
        self.config = config
        self.debug_file = debug_file
        self.netuid = None
        self.node_uid = None

    def initialize_metrics(self):
        print("Initializing PrometheusMetrics")
        if self.config:
            wallet = bt.wallet(config=self.config)
            subtensor = bt.subtensor(config=self.config)
            metagraph = subtensor.metagraph(self.config.netuid)
            self.netuid = self.config.netuid
            self.node_uid = metagraph.hotkeys.index(wallet.hotkey.ss58_address)
        else:
            self.netuid = None
            self.node_uid = None

        # Clear previous metrics to avoid duplication
        self.clear_registry()

        # Define Prometheus metrics with additional labels
        self.function_duration = Gauge(
            'function_duration_seconds', 
            'Duration of function calls', 
            ['function_name', 'netuid', 'node_uid', 'status', 'timestamp']
        )
        self.function_call_count = Counter(
            'function_call_count', 
            'Number of function calls', 
            ['function_name', 'netuid', 'node_uid', 'timestamp']
        )
        self.function_error_count = Counter(
            'function_error_count', 
            'Number of function errors', 
            ['function_name', 'netuid', 'node_uid', 'timestamp']
        )

    def clear_registry(self):
        """Clear the default registry to avoid metric duplication."""
        collectors = list(REGISTRY._collector_to_names.keys())
        for collector in collectors:
            REGISTRY.unregister(collector)

    def log_debug_data(self, function_name, duration, status, timestamp):
        """Log metrics data to a file for debugging purposes."""
        debug_data = {
            'function_name': function_name,
            'netuid': self.netuid,
            'node_uid': self.node_uid,
            'duration': duration,
            'status': status,
            'timestamp': timestamp
        }
        try:
            with open(self.debug_file, 'a') as f:  # Open in append mode
                f.write(json.dumps(debug_data) + '\n')
                f.flush()  # Ensure the data is written to disk
        except Exception as e:
            print(f"Failed to write log data: {e}")

    def instrument(self, func):
        """Decorator to instrument a function for Prometheus metrics."""
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                try:
                    timestamp = datetime.utcnow().isoformat()
                    self.function_call_count.labels(
                        function_name=func.__name__, 
                        netuid=self.netuid, 
                        node_uid=self.node_uid, 
                        timestamp=timestamp
                    ).inc()

                    start_time = time()
                    try:
                        result = await func(*args, **kwargs)
                        status = '1'  # Success
                        return result
                    except Exception as e:
                        status = '0'  # Failure
                        self.function_error_count.labels(
                            function_name=func.__name__, 
                            netuid=self.netuid, 
                            node_uid=self.node_uid, 
                            timestamp=timestamp
                        ).inc()
                        raise e
                    finally:
                        duration = time() - start_time
                        self.function_duration.labels(
                            function_name=func.__name__, 
                            netuid=self.netuid, 
                            node_uid=self.node_uid, 
                            status=status, 
                            timestamp=timestamp
                        ).set(duration)
                        # Log the metric data for debugging
                        self.log_debug_data(func.__name__, duration, status, timestamp)
                except Exception as e:
                    print(f"Metrics initialization not complete: {e}")
                    return await func(*args, **kwargs)
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                try:
                    timestamp = datetime.utcnow().isoformat()
                    self.function_call_count.labels(
                        function_name=func.__name__, 
                        netuid=self.netuid, 
                        node_uid=self.node_uid, 
                        timestamp=timestamp
                    ).inc()

                    start_time = time()
                    try:
                        result = func(*args, **kwargs)
                        status = '1'  # Success
                        return result
                    except Exception as e:
                        status = '0'  # Failure
                        self.function_error_count.labels(
                            function_name=func.__name__, 
                            netuid=self.netuid, 
                            node_uid=self.node_uid, 
                            timestamp=timestamp
                        ).inc()
                        raise e
                    finally:
                        duration = time() - start_time
                        self.function_duration.labels(
                            function_name=func.__name__, 
                            netuid=self.netuid, 
                            node_uid=self.node_uid, 
                            status=status, 
                            timestamp=timestamp
                        ).set(duration)
                        # Log the metric data for debugging
                        self.log_debug_data(func.__name__, duration, status, timestamp)
                except Exception as e:
                    print(f"Metrics initialization not complete: {e}")
                    return func(*args, **kwargs)
            return sync_wrapper

# Singleton instance
_prometheus_metrics = None

def initialize_metrics(config, debug_file='metrics_debug.log'):
    global _prometheus_metrics
    if _prometheus_metrics is None:
        _prometheus_metrics = PrometheusMetrics(config=config, debug_file=debug_file)
        _prometheus_metrics.initialize_metrics()

def get_prometheus_metrics():
    if _prometheus_metrics is None:
        raise Exception("PrometheusMetrics not initialized. Call initialize_metrics() first.")
    return _prometheus_metrics

def instrument(func):
    try:
        metrics = get_prometheus_metrics()
        return metrics.instrument(func)
    except Exception as e:
        print(f"Error initializing metrics for {func.__name__}: {e}")
        return func
