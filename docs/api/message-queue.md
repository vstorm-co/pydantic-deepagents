# Message Queue API

The message queue injects messages into a running agent — *steering* (delivered
before the next model request) or *follow-up* (delivered when the agent would
otherwise stop). Pass one via `message_queue=` on
[`create_deep_agent`][pydantic_deep.agent.create_deep_agent]. See
[Message queue (steering)](../advanced/message-queue.md) for the overview.

## MessageQueue

::: pydantic_deep.features.message_queue.MessageQueue
    options:
      show_source: false

## MessageQueueCapability

::: pydantic_deep.features.message_queue.MessageQueueCapability
    options:
      show_source: false

## run_with_queue

::: pydantic_deep.features.message_queue.run_with_queue
    options:
      show_source: false
