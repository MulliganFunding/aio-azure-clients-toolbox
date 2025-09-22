# Configuration

Advanced configuration options for Azure clients and connection pooling.

## Connection Pool Configuration

### Basic Parameters

```python
from aio_azure_clients_toolbox import ManagedCosmos

client = ManagedCosmos(
    endpoint="https://cosmos.documents.azure.com/",
    dbname="database",
    container_name="container",
    credential=credential,
    # Connection pool settings
    client_limit=100,           # Clients per connection
    max_size=10,                # Pool size
    max_idle_seconds=300,       # 5 minute idle timeout
    max_lifespan_seconds=3600   # 1 hour max lifetime
)
```

### Parameter Guidelines

#### client_limit

Number of concurrent clients that can share a single connection.

- **Default**: 100
- **Azure Recommendation**: Up to 100 for most services
- **Low Latency**: 50-75 for minimal contention
- **High Throughput**: 100-200 if service supports it

```python
# Conservative configuration
client_limit=50

# High-throughput configuration
client_limit=200
```

#### max_size

Maximum number of connections in the pool.

- **Default**: 10
- **Small Applications**: 2-5 connections
- **Medium Applications**: 5-15 connections
- **Large Applications**: 15-50 connections

```python
# Memory-constrained environment
max_size=3

# High-concurrency application
max_size=25
```

#### max_idle_seconds

Time before idle connections are recycled.

- **Default**: 300 seconds (5 minutes)
- **Frequent Access**: 60-300 seconds
- **Infrequent Access**: 600-1800 seconds
- **Cost Optimization**: 30-60 seconds

```python
# Quick recycling for cost optimization
max_idle_seconds=60

# Longer retention for performance
max_idle_seconds=900  # 15 minutes
```

#### max_lifespan_seconds

Maximum connection lifetime before forced recycling.

- **Default**: None (no limit)
- **Recommended**: 3600-7200 seconds (1-2 hours)
- **Security**: 1800 seconds (30 minutes) for sensitive data
- **Stability**: 86400 seconds (24 hours) for stable environments

```python
# Frequent rotation for security
max_lifespan_seconds=1800

# Balanced rotation
max_lifespan_seconds=3600
```

## Service-Specific Configuration

### Cosmos DB

```python
# Low-latency configuration
cosmos_client = ManagedCosmos(
    endpoint=endpoint,
    dbname=database,
    container_name=container,
    credential=credential,
    client_limit=50,           # Lower contention
    max_size=5,                # Smaller pool
    max_idle_seconds=60,       # Quick recycling
    max_lifespan_seconds=1800  # 30-minute rotation
)

# High-throughput configuration
cosmos_client = ManagedCosmos(
    endpoint=endpoint,
    dbname=database,
    container_name=container,
    credential=credential,
    client_limit=200,          # Maximum sharing
    max_size=20,               # Large pool
    max_idle_seconds=300,      # Standard timeout
    max_lifespan_seconds=7200  # 2-hour rotation
)
```

### Service Bus

```python
# Message processing optimization
service_bus = ManagedAzureServiceBusSender(
    service_bus_namespace_url=namespace_url,
    service_bus_queue_name=queue_name,
    credential=credential,
    client_limit=100,          # Standard sharing
    max_size=15,               # Medium pool for message bursts
    max_idle_seconds=120,      # Quick idle timeout
    max_lifespan_seconds=3600  # 1-hour rotation
)
```

### Event Hub

```python
# Event streaming optimization
eventhub = ManagedAzureEventhubProducer(
    eventhub_namespace=namespace,
    eventhub_name=hub_name,
    credential=credential,
    client_limit=150,          # Higher sharing for events
    max_size=10,               # Standard pool
    max_idle_seconds=180,      # 3-minute timeout
    max_lifespan_seconds=5400, # 90-minute rotation
    ready_message='{"type": "health_check"}'
)
```

## Environment-Based Configuration

### Configuration Class

```python
import os
from dataclasses import dataclass
from azure.identity.aio import DefaultAzureCredential

@dataclass
class AzureConfig:
    """Centralized Azure configuration."""

    # Connection pool settings
    client_limit: int = 100
    max_size: int = 10
    max_idle_seconds: int = 300
    max_lifespan_seconds: int = 3600

    # Service endpoints
    cosmos_endpoint: str = None
    cosmos_database: str = None
    storage_account_url: str = None
    service_bus_namespace: str = None
    eventhub_namespace: str = None

    @classmethod
    def from_environment(cls) -> 'AzureConfig':
        """Load configuration from environment variables."""
        return cls(
            # Pool configuration
            client_limit=int(os.getenv('AZURE_CLIENT_LIMIT', '100')),
            max_size=int(os.getenv('AZURE_POOL_SIZE', '10')),
            max_idle_seconds=int(os.getenv('AZURE_IDLE_TIMEOUT', '300')),
            max_lifespan_seconds=int(os.getenv('AZURE_LIFESPAN', '3600')),

            # Service endpoints
            cosmos_endpoint=os.getenv('COSMOS_ENDPOINT'),
            cosmos_database=os.getenv('COSMOS_DATABASE'),
            storage_account_url=os.getenv('STORAGE_ACCOUNT_URL'),
            service_bus_namespace=os.getenv('SERVICE_BUS_NAMESPACE'),
            eventhub_namespace=os.getenv('EVENTHUB_NAMESPACE')
        )

    def get_credential(self) -> DefaultAzureCredential:
        """Get Azure credential."""
        return DefaultAzureCredential()
```

### Usage with Configuration

```python
# Load configuration
config = AzureConfig.from_environment()

# Create clients with shared configuration
cosmos_client = ManagedCosmos(
    endpoint=config.cosmos_endpoint,
    dbname=config.cosmos_database,
    container_name="users",
    credential=config.get_credential(),
    client_limit=config.client_limit,
    max_size=config.max_size,
    max_idle_seconds=config.max_idle_seconds,
    max_lifespan_seconds=config.max_lifespan_seconds
)

blob_client = AzureBlobStorageClient(
    az_storage_url=config.storage_account_url,
    container_name="documents",
    credential=config.get_credential()
)
```

## Environment Variables

### Standard Variables

```bash
# Azure Authentication
export AZURE_CLIENT_ID="your-client-id"
export AZURE_CLIENT_SECRET="your-client-secret"
export AZURE_TENANT_ID="your-tenant-id"

# Service Endpoints
export COSMOS_ENDPOINT="https://your-cosmos.documents.azure.com:443/"
export COSMOS_DATABASE="your-database"
export STORAGE_ACCOUNT_URL="https://yourstorage.blob.core.windows.net"
export SERVICE_BUS_NAMESPACE="https://your-sb.servicebus.windows.net"
export EVENTHUB_NAMESPACE="your-eventhub-namespace"

# Connection Pool Settings
export AZURE_CLIENT_LIMIT="100"
export AZURE_POOL_SIZE="10"
export AZURE_IDLE_TIMEOUT="300"
export AZURE_LIFESPAN="3600"
```

### Environment-Specific Overrides

```bash
# Development environment
export AZURE_CLIENT_LIMIT="25"
export AZURE_POOL_SIZE="3"
export AZURE_IDLE_TIMEOUT="60"

# Production environment
export AZURE_CLIENT_LIMIT="200"
export AZURE_POOL_SIZE="20"
export AZURE_IDLE_TIMEOUT="300"
export AZURE_LIFESPAN="7200"

# Testing environment
export AZURE_CLIENT_LIMIT="10"
export AZURE_POOL_SIZE="2"
export AZURE_IDLE_TIMEOUT="30"
```

## Configuration Validation

```python
class ConfigValidator:
    """Validate Azure configuration parameters."""

    @staticmethod
    def validate_pool_config(client_limit: int, max_size: int,
                           max_idle_seconds: int, max_lifespan_seconds: int = None):
        """Validate connection pool configuration."""

        if client_limit < 1:
            raise ValueError("client_limit must be positive")

        if client_limit > 500:
            raise ValueError("client_limit should not exceed 500")

        if max_size < 1:
            raise ValueError("max_size must be positive")

        if max_size > 100:
            raise ValueError("max_size should not exceed 100")

        if max_idle_seconds < 10:
            raise ValueError("max_idle_seconds should be at least 10 seconds")

        if max_lifespan_seconds is not None:
            if max_lifespan_seconds < max_idle_seconds:
                raise ValueError("max_lifespan_seconds must be greater than max_idle_seconds")

    @staticmethod
    def validate_endpoints(config: AzureConfig):
        """Validate service endpoints."""

        if config.cosmos_endpoint and not config.cosmos_endpoint.startswith('https://'):
            raise ValueError("Cosmos endpoint must use HTTPS")

        if config.storage_account_url and not config.storage_account_url.startswith('https://'):
            raise ValueError("Storage account URL must use HTTPS")

        if config.service_bus_namespace and not config.service_bus_namespace.startswith('https://'):
            raise ValueError("Service Bus namespace must use HTTPS")

# Usage
config = AzureConfig.from_environment()
ConfigValidator.validate_pool_config(
    config.client_limit,
    config.max_size,
    config.max_idle_seconds,
    config.max_lifespan_seconds
)
ConfigValidator.validate_endpoints(config)
```

## Dynamic Configuration

### Runtime Configuration Updates

```python
class DynamicAzureConfig:
    """Configuration that can be updated at runtime."""

    def __init__(self, initial_config: AzureConfig):
        self._config = initial_config
        self._clients = {}
        self._update_lock = asyncio.Lock()

    async def update_pool_config(self, **kwargs):
        """Update pool configuration and recreate clients."""
        async with self._update_lock:
            # Update configuration
            for key, value in kwargs.items():
                if hasattr(self._config, key):
                    setattr(self._config, key, value)

            # Validate new configuration
            ConfigValidator.validate_pool_config(
                self._config.client_limit,
                self._config.max_size,
                self._config.max_idle_seconds,
                self._config.max_lifespan_seconds
            )

            # Close existing clients
            for client in self._clients.values():
                if hasattr(client, 'close'):
                    await client.close()

            # Clear client cache
            self._clients.clear()

    def get_cosmos_client(self, container_name: str) -> ManagedCosmos:
        """Get Cosmos client with current configuration."""
        key = f"cosmos_{container_name}"

        if key not in self._clients:
            self._clients[key] = ManagedCosmos(
                endpoint=self._config.cosmos_endpoint,
                dbname=self._config.cosmos_database,
                container_name=container_name,
                credential=self._config.get_credential(),
                client_limit=self._config.client_limit,
                max_size=self._config.max_size,
                max_idle_seconds=self._config.max_idle_seconds,
                max_lifespan_seconds=self._config.max_lifespan_seconds
            )

        return self._clients[key]
```

## Performance Tuning

### Monitoring Configuration Impact

```python
import time
import asyncio
from collections import defaultdict

class PerformanceMonitor:
    """Monitor performance impact of configuration changes."""

    def __init__(self):
        self.metrics = defaultdict(list)
        self.start_times = {}

    def start_operation(self, operation_id: str):
        """Start timing an operation."""
        self.start_times[operation_id] = time.time()

    def end_operation(self, operation_id: str, operation_type: str):
        """End timing an operation."""
        if operation_id in self.start_times:
            duration = time.time() - self.start_times[operation_id]
            self.metrics[operation_type].append(duration)
            del self.start_times[operation_id]

    def get_stats(self, operation_type: str) -> dict:
        """Get performance statistics."""
        durations = self.metrics[operation_type]
        if not durations:
            return {}

        return {
            "count": len(durations),
            "avg_duration": sum(durations) / len(durations),
            "min_duration": min(durations),
            "max_duration": max(durations),
            "total_duration": sum(durations)
        }

# Usage
monitor = PerformanceMonitor()

# Wrap client operations
async def monitored_cosmos_operation(client, document):
    operation_id = f"cosmos_{time.time()}"
    monitor.start_operation(operation_id)

    try:
        async with client.get_container_client() as container:
            result = await container.create_item(body=document)
        return result
    finally:
        monitor.end_operation(operation_id, "cosmos_create")

# Analyze performance
stats = monitor.get_stats("cosmos_create")
print(f"Average operation time: {stats['avg_duration']:.3f}s")
```

### Configuration Optimization

```python
async def optimize_configuration(base_config: AzureConfig,
                               test_workload, iterations: int = 100):
    """Find optimal configuration through testing."""

    configs_to_test = [
        # Conservative
        {"client_limit": 25, "max_size": 3, "max_idle_seconds": 60},
        # Balanced
        {"client_limit": 100, "max_size": 10, "max_idle_seconds": 300},
        # Aggressive
        {"client_limit": 200, "max_size": 20, "max_idle_seconds": 600}
    ]

    results = []

    for config_override in configs_to_test:
        # Create test configuration
        test_config = AzureConfig(
            **{**base_config.__dict__, **config_override}
        )

        # Run performance test
        start_time = time.time()

        try:
            await test_workload(test_config, iterations)
            duration = time.time() - start_time

            results.append({
                "config": config_override,
                "duration": duration,
                "ops_per_second": iterations / duration
            })

        except Exception as e:
            results.append({
                "config": config_override,
                "error": str(e)
            })

    # Find best configuration
    valid_results = [r for r in results if "error" not in r]
    if valid_results:
        best = max(valid_results, key=lambda x: x["ops_per_second"])
        return best["config"]

    return None
```