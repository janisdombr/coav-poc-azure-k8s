# datetime: 2026-06-26
from pyspark.sql.functions import col, from_json, expr
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, IntegerType, BooleanType
import re, sys

# Get the Event Hub connection string from Databricks Secrets
connection_string = dbutils.secrets.get(scope="coav-secrets", key="eventhub-conn-str").strip()

# Build Kafka config — DBR 14.3+ uses shaded Kafka, requires kafkashaded prefix in JAAS
eh_namespace = re.search(r'sb://(.*?)\.servicebus\.windows\.net', connection_string).group(1)
eh_conf = {
    "kafka.bootstrap.servers":                      f"{eh_namespace}.servicebus.windows.net:9093",
    "kafka.security.protocol":                      "SASL_SSL",
    "kafka.sasl.mechanism":                         "PLAIN",
    "kafka.sasl.jaas.config":                       (
        'kafkashaded.org.apache.kafka.common.security.plain.PlainLoginModule required '
        'username="$ConnectionString" '
        'password="' + connection_string + '";'
    ),
    "kafka.ssl.endpoint.identification.algorithm":  "https",
    "kafka.group.id":                               "databricks-coav-stream",
    "subscribe":                                    "telemetry-adsb-inbound",
    "startingOffsets":                              "latest",
    "failOnDataLoss":                               "false",
}

# create managed database if it doesn't exist
spark.sql("CREATE DATABASE IF NOT EXISTS coav_dw")

# Schemas
# Strict structural definition for flight telemetry (ADSB)
telemetry_schema = StructType([
    StructField("message_type", StringType(), True),
    StructField("flight_id", StringType(), True),
    StructField("timestamp", StringType(), True),
    StructField("latitude", DoubleType(), True),
    StructField("longitude", DoubleType(), True),
    StructField("altitude_ft", IntegerType(), True)
])

# Strict structural definition for Edge AI camera detection logs
ai_schema = StructType([
    StructField("message_type", StringType(), True),
    StructField("flight_id", StringType(), True),
    StructField("timestamp", StringType(), True),
    StructField("camera_id", StringType(), True),
    StructField("contrail_detected", BooleanType(), True),
    StructField("confidence_score", DoubleType(), True)
])

# ==============================================================================
# LAYER 1: BRONZE (Raw ingestion from Event Hub into Append-Only Delta Table)
# ==============================================================================
# Read via Kafka protocol — field is "value" (not "body"), aliased to "body" for downstream compatibility
df_raw_stream = spark.readStream \
    .format("kafka") \
    .options(**eh_conf) \
    .load() \
    .withColumn("body", col("value").cast("string"))

# Write directly to Bronze table with raw string payloads
query_bronze = df_raw_stream.writeStream \
    .format("delta") \
    .outputMode("append") \
    .option("checkpointLocation", "file:/local_disk0/checkpoints/bronze") \
    .toTable("coav_dw.bronze_events")

# ==============================================================================
# LAYER 2: SILVER (Stream-Stream Join, Schema Validation & Enrichment)
# ==============================================================================
# Read back from Bronze table as a stream to separate and clear raw events
df_bronze_source = spark.readStream.table("coav_dw.bronze_events")

# Branch A: ADSB Telemetry stream with 5-minute event watermark
df_adsb = df_bronze_source \
    .withColumn("parsed", from_json(col("body"), telemetry_schema)) \
    .select("parsed.*") \
    .filter(col("message_type") == "ADSB_TELEMETRY") \
    .withColumn("event_time", col("timestamp").cast("timestamp")) \
    .withWatermark("event_time", "5 minutes") \
    .alias("a")

# Branch B: Edge AI vision stream with 5-minute event watermark
df_vision = df_bronze_source \
    .withColumn("parsed", from_json(col("body"), ai_schema)) \
    .select("parsed.*") \
    .filter(col("message_type") == "EDGE_VISION_AI") \
    .withColumn("ai_time", col("timestamp").cast("timestamp")) \
    .withWatermark("ai_time", "5 minutes") \
    .alias("v")

# Stream-Stream Inner Join based on flight_id and a tight time window (-1 to +3 mins)
df_joined_silver = df_adsb.join(
    df_vision,
    expr("""
        a.flight_id = v.flight_id AND
        v.ai_time >= a.event_time - interval 1 minute AND
        v.ai_time <= a.event_time + interval 3 minutes
    """)
).select(
    col("a.flight_id"),
    col("a.event_time").alias("timestamp"),
    col("a.latitude"),
    col("a.longitude"),
    col("a.altitude_ft"),
    col("v.camera_id"),
    col("v.contrail_detected"),
    col("v.confidence_score")
)

# Persist enriched telemetry + vision data into Silver Table
query_silver = df_joined_silver.writeStream \
    .format("delta") \
    .outputMode("append") \
    .option("checkpointLocation", "file:/local_disk0/checkpoints/silver_enriched") \
    .toTable("coav_dw.silver_matched_traffic")

# ==============================================================================
# LAYER 3: GOLD (Aggregated Analytics Layer for Eco-Monitoring / ISSR validation)
# ==============================================================================
# Aggregating verified contrails for downstream BI or mapping tools
df_silver_source = spark.readStream.table("coav_dw.silver_matched_traffic")

df_gold_issr = df_silver_source \
    .filter((col("contrail_detected") == True) & (col("confidence_score") > 0.85)) \
    .groupBy("latitude", "longitude", "altitude_ft") \
    .count()

# Write running analytical aggregations directly to Gold layer
query_gold = df_gold_issr.writeStream \
    .format("delta") \
    .outputMode("complete") \
    .option("checkpointLocation", "file:/local_disk0/checkpoints/gold_issr") \
    .toTable("coav_dw.gold_verified_issr_zones")

# Wait for termination to keep the streaming job active in Databricks compute context
spark.streams.awaitAnyTermination()