# Monitoring API

The Monitor feature lets the agent watch a long-lived command and react to new
output without polling. Enabled via `include_monitoring=True` on
[`create_deep_agent`][pydantic_deep.agent.create_deep_agent]. See
[Monitor — watch & react](../advanced/monitor.md) for the overview.

## MonitorManager

::: pydantic_deep.features.monitoring.MonitorManager
    options:
      show_source: false

## MonitorEvent

::: pydantic_deep.features.monitoring.MonitorEvent
    options:
      show_source: false

## MonitorInfo

::: pydantic_deep.features.monitoring.MonitorInfo
    options:
      show_source: false

## create_monitor_toolset

::: pydantic_deep.features.monitoring.create_monitor_toolset
    options:
      show_source: false
