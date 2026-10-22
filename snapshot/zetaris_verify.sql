SELECT package_name, version, publisher, install_scripts, dep_count, source FROM pkgtrail.releases_table WHERE (package_name = 'event-stream' AND version IN ('3.3.5','3.3.6')) OR (package_name = 'ua-parser-js' AND version = '0.7.29') OR (package_name = 'node-ipc' AND version = '12.0.1');
SELECT source, COUNT(*) AS n FROM pkgtrail.releases_table GROUP BY source;
SELECT dependency, version_range, source FROM pkgtrail.dependencies_table WHERE package_name = 'event-stream' AND version = '3.3.6' AND dependency = 'flatmap-stream'
