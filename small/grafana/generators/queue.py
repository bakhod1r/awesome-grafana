"""Queue: message brokers (container.type=queue). RabbitMQ from its built-in Prometheus plugin (job rabbitmq,
/metrics/per-object), Kafka from kafka_exporter (danielqsj), NATS JetStream from prometheus-nats-exporter.
Sections for brokers that are not running stay empty with a note."""
from lib import *

UID, SLUG = "queue", "queue"
I = 'instance=~"$instance"'
Q = f'{I}, queue=~"$queue"'

d = Dash(UID, "Queue",
         "Message brokers: is work piling up, are consumers keeping up, are messages lost. "
         "RabbitMQ (built-in plugin), Kafka (kafka_exporter), NATS JetStream (nats exporter). Opened for containers labelled container.type=queue.",
         ["queue", "rabbitmq", "kafka", "services"], time_from="now-3h",
         variables=[project_var(), container_var(),
                    query_var("instance", "RabbitMQ", 'label_values(rabbitmq_identity_info{project=~"$project"}, instance)', desc="RabbitMQ node."),
                    query_var("queue", "Queue", 'label_values(rabbitmq_queue_messages_ready{instance=~"$instance"}, queue)')])

health_row(d, "queue")


def empty(p, note):
    p["fieldConfig"]["defaults"]["noValue"] = note
    return p


NO_RMQ = "No RabbitMQ scraped (prometheus/exporters/rabbitmq.yml)"
d.row("RabbitMQ — is work piling up?")
d.add(stat("Messages waiting", f"sum(rabbitmq_queue_messages_ready{{{Q}}})", color_mode="value", th=steps((1000, "orange"), (10000, "red")),
           desc="Ready, not yet delivered. Growing = consumers too slow or down."), 4, 4)
d.add(stat("Unacked", f"sum(rabbitmq_queue_messages_unacked{{{Q}}})", color_mode="value", th=steps((500, "orange")),
           desc="Delivered, consumer has not confirmed yet. High = slow or stuck consumers."), 4, 4)
d.add(stat("Publish/s", f"sum(rate(rabbitmq_queue_messages_published_total{{{Q}}}[5m]))", unit="ops", color_mode="value", th=steps(base="blue")), 4, 4)
d.add(stat("Deliver/s", f"sum(rate(rabbitmq_channel_messages_delivered_ack_total{{{I}}}[5m])) + sum(rate(rabbitmq_channel_messages_delivered_total{{{I}}}[5m]))",
           unit="ops", color_mode="value", th=steps(base="blue")), 4, 4)
d.add(stat("Consumers", f"sum(rabbitmq_queue_consumers{{{Q}}})", color_mode="value", th=steps((1, "green"), base="red"),
           desc="0 consumers on a queue = nothing processes it."), 4, 4)
d.add(stat("Time to drain", f"sum(rabbitmq_queue_messages_ready{{{Q}}}) / (sum(rate(rabbitmq_channel_messages_acked_total{{{I}}}[5m])) > 0)",
           unit="s", decimals=0, th=steps((300, "orange"), (3600, "red")),
           desc="Backlog / ack rate: how long consumers need to empty the queues if no new messages arrive."), 4, 4)

d.add(empty(ts("Messages waiting by queue", [tgt(f"sum by (queue) (rabbitmq_queue_messages_ready{{{Q}}})", "{{queue}}")],
               desc="Steady climb = consumers can't keep up. Saw-tooth = batch consumers (fine)."), NO_RMQ), 12, 9)
d.add(empty(ts("In vs out (msg/s)", [tgt(f"sum(rate(rabbitmq_queue_messages_published_total{{{Q}}}[5m]))", "published"),
                                     tgt(f"sum(rate(rabbitmq_channel_messages_acked_total{{{I}}}[5m]))", "acked (done)"),
                                     tgt(f"sum(rate(rabbitmq_channel_messages_redelivered_total{{{I}}}[5m]))", "redelivered (retries)")],
               unit="ops", fill=0, desc="published above acked for long = backlog grows. Redelivered = consumers failing or crashing."), NO_RMQ), 12, 9)
d.add(empty(ts("Unacked by queue", [tgt(f"sum by (queue) (rabbitmq_queue_messages_unacked{{{Q}}})", "{{queue}}")]), NO_RMQ), 12, 9)
d.add(empty(ts("Consumers and consumer utilisation", [tgt(f"sum by (queue) (rabbitmq_queue_consumers{{{Q}}})", "{{queue}} consumers"),
                                                      tgt(f"avg by (queue) (rabbitmq_queue_consumer_utilisation{{{Q}}}) * 100", "{{queue}} utilisation %")],
               fill=0, desc="Utilisation under 100% with a backlog = prefetch too low or consumers slow."), NO_RMQ), 12, 9)
d.add(empty(ts("Dead-lettered and dropped (msg/s)", [
    tgt(f"sum(rate(rabbitmq_global_messages_dead_lettered_rejected_total{{{I}}}[5m]))", "dead-lettered: rejected"),
    tgt(f"sum(rate(rabbitmq_global_messages_dead_lettered_expired_total{{{I}}}[5m]))", "dead-lettered: expired (TTL)"),
    tgt(f"sum(rate(rabbitmq_global_messages_dead_lettered_maxlen_total{{{I}}}[5m]))", "dead-lettered: queue full"),
    tgt(f"sum(rate(rabbitmq_global_messages_unroutable_dropped_total{{{I}}}[5m]))", "dropped: unroutable")],
    unit="ops", fill=0, desc="Messages that did not reach a consumer. Unroutable = published to an exchange with no matching queue."), NO_RMQ), 12, 9)
d.add(empty(ts("Queue size (bytes)", [tgt(f"sum by (queue) (rabbitmq_queue_messages_bytes{{{Q}}})", "{{queue}}")], unit="bytes"), NO_RMQ), 12, 9)

d.row("RabbitMQ — node")
d.add(stat("Memory vs high watermark", f"sum(rabbitmq_process_resident_memory_bytes{{{I}}}) / sum(rabbitmq_resident_memory_limit_bytes{{{I}}}) * 100",
           unit="percent", decimals=0, th=steps((70, "orange"), (90, "red")), desc="At 100% RabbitMQ blocks all publishers."), 6, 4)
d.add(stat("Free disk vs limit", f"min(rabbitmq_disk_space_available_bytes{{{I}}} / rabbitmq_disk_space_available_limit_bytes{{{I}}})",
           unit="x", decimals=1, th=steps((2, "orange"), (5, "green"), base="red"), desc="Below 1x RabbitMQ blocks publishers (disk alarm)."), 6, 4)
d.add(stat("Connections", f"sum(rabbitmq_connections{{{I}}})", color_mode="value", th=steps(base="blue")), 6, 4)
d.add(stat("File descriptors used", f"sum(rabbitmq_process_open_fds{{{I}}}) / sum(rabbitmq_process_max_fds{{{I}}}) * 100", unit="percent", decimals=0,
           th=steps((70, "orange"), (90, "red"))), 6, 4)
d.add(empty(ts("Connections and channels", [tgt(f"sum(rabbitmq_connections{{{I}}})", "connections"), tgt(f"sum(rabbitmq_channels{{{I}}})", "channels"),
                                            tgt(f"sum(rate(rabbitmq_connections_opened_total{{{I}}}[5m])) * 60", "connections opened/min")], fill=0,
               desc="Many opened/min = clients reconnect for every message (expensive)."), NO_RMQ), 12, 8)
d.add(empty(ts("Memory", [tgt(f"sum(rabbitmq_process_resident_memory_bytes{{{I}}})", "used"),
                          tgt(f"sum(rabbitmq_resident_memory_limit_bytes{{{I}}})", "high watermark")], unit="bytes", fill=0), NO_RMQ), 12, 8)

NO_KAFKA = "No Kafka exporter (kafka_exporter) scraped"
d.row("Kafka", collapsed=True)
d.add(empty(ts("Consumer lag by group", [tgt('sum by (consumergroup) (kafka_consumergroup_lag{project=~"$project"})', "{{consumergroup}}")],
               desc="Messages a consumer group is behind. Growing = consumers too slow."), NO_KAFKA), 12, 8)
d.add(empty(ts("Messages in/s by topic", [tgt('sum by (topic) (rate(kafka_topic_partition_current_offset{project=~"$project"}[5m]))', "{{topic}}")], unit="ops"), NO_KAFKA), 12, 8)
d.add(empty(ts("Under-replicated partitions", [tgt('sum(kafka_topic_partition_under_replicated_partition{project=~"$project"})', "under-replicated")],
               desc="Above 0 = a broker is down or slow; data at risk."), NO_KAFKA), 12, 8)
d.add(empty(ts("Brokers", [tgt('max(kafka_brokers{project=~"$project"})', "brokers")]), NO_KAFKA), 12, 8)

NO_NATS = "No NATS exporter scraped"
d.row("NATS JetStream", collapsed=True)
d.add(empty(ts("Pending messages by consumer", [tgt('sum by (consumer_name) (jetstream_consumer_num_pending{project=~"$project"})', "{{consumer_name}}")]), NO_NATS), 12, 8)
d.add(empty(ts("Stream messages", [tgt('sum by (stream_name) (jetstream_stream_total_messages{project=~"$project"})', "{{stream_name}}")]), NO_NATS), 12, 8)

d.row("Logs")
d.add(logs("Errors and warnings", f'{type_logs("queue")} level:(error OR fatal OR panic OR warn) | sort by (_time desc) | limit 300'), 24, 10)

d.write("Apps/queue.json")
