# datetime: 2026-06-25
from pyspark.sql.functions import col, from_json, expr
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, IntegerType, BooleanType

# Get the Event Hub connection string from Databricks Secrets
connection_string = dbutils.secrets.get(scope="coav-secrets", key="eventhub-conn-str")
eh_conf = {
    'eventhubs.connectionString': connection_string
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
df_raw_stream = spark.readStream \
    .format("eventhubs") \
    .options(**eh_conf) \
    .load() \
    .withColumn("body", col("body").cast("string"))

# Write directly to Bronze table with raw string payloads
query_bronze = df_raw_stream.writeStream \
    .format("delta") \
    .outputMode("append") \
    .option("checkpointLocation", "/mnt/telemetry/checkpoints/bronze") \
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
    .withWatermark("event_time", "5 minutes")

# Branch B: Edge AI vision stream with 5-minute event watermark
df_vision = df_bronze_source \
    .withColumn("parsed", from_json(col("body"), ai_schema)) \
    .select("parsed.*") \
    .filter(col("message_type") == "EDGE_VISION_AI") \
    .withColumn("ai_time", col("timestamp").cast("timestamp")) \
    .withWatermark("ai_time", "5 minutes")

# Stream-Stream Inner Join based on flight_id and a tight time window (-1 to +3 mins)
df_joined_silver = df_adsb.join(
    df_vision,
    expr("""
        df_adsb.flight_id = df_vision.flight_id AND
        df_vision.ai_time >= df_adsb.event_time - interval 1 minute AND
        df_vision.ai_time <= df_adsb.event_time + interval 3 minutes
    """)
).select(
    df_adsb.flight_id,
    df_adsb.event_time.alias("timestamp"),
    df_adsb.latitude,
    df_adsb.longitude,
    df_adsb.altitude_ft,
    df_vision.camera_id,
    df_vision.contrail_detected,
    df_vision.confidence_score
)

# Persist enriched telemetry + vision data into Silver Table
query_silver = df_joined_silver.writeStream \
    .format("delta") \
    .outputMode("append") \
    .option("checkpointLocation", "/mnt/telemetry/checkpoints/silver_enriched") \
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
    .option("checkpointLocation", "/mnt/telemetry/checkpoints/gold_issr") \
    .toTable("coav_dw.gold_verified_issr_zones")

# Wait for termination to keep the streaming job active in Databricks compute context
spark.streams.awaitAnyTermination()