import polars as pl
from .tools import human_duration



class ChunkStatistics:
    def __init__(self, df: pl.DataFrame) -> None:
        self.df = df

    @property
    def sessions(self) -> int:
        return self.df.height
    @property
    def total_seconds(self) -> int:
        if self.df.is_empty():
            return 0

        return (
            self.df
            .select(pl.sum("duration_seconds"))
            .item()
        )

    @property
    def total_hours(self) -> float:
        return self.total_seconds / 3600

    @property
    def average_seconds(self) -> float:
        if self.df.is_empty():
            return 0

        return (
            self.df
            .select(pl.mean("duration_seconds"))
            
            .item()
        )

    @property
    def median_seconds(self):
        if self.df.is_empty():
            return 0

        return (
            self.df
            .select(pl.median("duration_seconds"))
            
            .item()
        )
    @property
    def minimum_seconds(self):
        if self.df.is_empty():
            return 0

        return (
            self.df
            .select(pl.min("duration_seconds"))
            
            .item()
        )
    @property
    def maximum_seconds(self):
        if self.df.is_empty():
            return 0

        return (
            self.df
            .select(pl.max("duration_seconds"))
            
            .item()
        )    
    @property
    def std_seconds(self):
        if self.df.is_empty():
            return 0

        return (
            self.df
            .select(pl.std("duration_seconds"))
            
            .item()
        )
    @property
    def daily(self):
        return (
            self.df
            .group_by(
                pl.col("start_timestamp").dt.date()
            )
            .agg(
                pl.sum("duration_seconds")
                    .alias("duration_seconds")
            )
            .sort("start_timestamp")
        )
    @property
    def daily_average_seconds(self):
        daily = self.daily

        if daily.is_empty():
            return 0

        return (
            daily
            .select(pl.mean("duration_seconds"))
            
            .item()
        )
    @property
    def longest(self):
        if self.df.is_empty():
            return None

        return (
            self.df
            .sort("duration_seconds", descending=True)
            .head(1)
            
        )  
    @property
    def shortest(self):
        if self.df.is_empty():
            return None

        return (
            self.df
            .sort("duration_seconds", descending=False)
            .head(1)
            
        )  

    def summary(self) -> pl.DataFrame:
        return pl.DataFrame({
            "Metric": [
                "Sessions",
                "Total time",
                "Total hours",
                "Average session",
                "Median session",
                "Shortest session",
                "Longest session",
                "Standard deviation",
            ],
            "Value": [
                str(self.sessions),
                human_duration(self.total_seconds),
                f"{self.total_hours:.2f} h",
                human_duration(self.average_seconds),
                human_duration(self.median_seconds),
                human_duration(self.minimum_seconds),
                human_duration(self.maximum_seconds),
                human_duration(self.std_seconds),
            ],
        })

    def by_activity(self) -> pl.DataFrame:
        """Aggregate statistics by activity."""

        return (
            self.df
            .group_by(["category", "name"])
            .agg(
                pl.len().alias("sessions"),
                pl.sum("duration_seconds").alias("total_seconds"),
                pl.mean("duration_seconds").alias("average_seconds"),
                pl.median("duration_seconds").alias("median_seconds"),
                pl.min("duration_seconds").alias("minimum_seconds"),
                pl.max("duration_seconds").alias("maximum_seconds"),
            )
            .sort("total_seconds", descending=True)
        )

    def by_category(self) -> pl.DataFrame:
        """Aggregate statistics by category."""

        return (
            self.df
            .group_by("category")
            .agg(
                pl.len().alias("sessions"),
                pl.sum("duration_seconds").alias("total_seconds"),
                pl.mean("duration_seconds").alias("average_seconds"),
                pl.median("duration_seconds").alias("median_seconds"),
                pl.min("duration_seconds").alias("minimum_seconds"),
                pl.max("duration_seconds").alias("maximum_seconds"),
            )
            .sort("total_seconds", descending=True)
        )

    def activity_share(self) -> pl.DataFrame:
        """Percentage of tracked time spent in each activity."""

        total = self.df["duration_seconds"].sum()

        if total == 0:
            return pl.DataFrame()

        return (
            self.df
            .group_by(["category", "name"])
            .agg(
                pl.sum("duration_seconds").alias("total_seconds"),
                pl.len().alias("sessions"),
            )
            .with_columns(
                (
                    pl.col("total_seconds") / total * 100
                ).alias("percent")
            )
            .sort("total_seconds", descending=True)
        )


    def longest_sessions(self, n: int = 10) -> pl.DataFrame:
        """Return the N longest sessions."""

        return (
            self.df
            .sort("duration_seconds", descending=True)
            .head(n)
        )


    def by_day(self) -> pl.DataFrame:
        """Statistics aggregated by calendar day."""

        return (
            self.df
            .with_columns(
                pl.col("start_timestamp").dt.date().alias("day")
            )
            .group_by("day")
            .agg(
                pl.len().alias("sessions"),
                pl.sum("duration_seconds").alias("total_seconds"),
                pl.mean("duration_seconds").alias("average_seconds"),
                pl.median("duration_seconds").alias("median_seconds"),
                pl.min("duration_seconds").alias("minimum_seconds"),
                pl.max("duration_seconds").alias("maximum_seconds"),
            )
            .sort("day")
        )


    def describe(self) -> pl.DataFrame:
        """Descriptive statistics of session durations."""

        return (
            self.df
            .select("duration_seconds")
            .describe()
        )