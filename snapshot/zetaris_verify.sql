SELECT package_name, version, published_at, publisher, removed FROM pkgtrail.releases_table WHERE package_name = 'event-stream' AND version IN ('3.3.4','3.3.5','3.3.6');
SELECT role, COUNT(*) AS n FROM pkgtrail.releases_table GROUP BY role;
SELECT COUNT(*) AS n FROM pkgtrail.maintainers_table;
SELECT COUNT(*) AS n FROM pkgtrail.dependencies_table
