CREATE LIGHTNING DATABASE PKGTRAIL_REST DESCRIBE BY "Package Trail npm snapshot, served by local serve_rows.py";
CREATE SCHEMASTORE CONTAINER pkgtrail;
CREATE LIGHTNING REST TABLE releases_raw FROM PKGTRAIL_REST REQUEST(endpoint "http://host.docker.internal:9000/releases", method "get", response_type "json", http_encoding "URLENCODED") HEADER () BODY ();
CREATE LIGHTNING REST TABLE maintainers_raw FROM PKGTRAIL_REST REQUEST(endpoint "http://host.docker.internal:9000/maintainers", method "get", response_type "json", http_encoding "URLENCODED") HEADER () BODY ();
CREATE LIGHTNING REST TABLE dependencies_raw FROM PKGTRAIL_REST REQUEST(endpoint "http://host.docker.internal:9000/dependencies", method "get", response_type "json", http_encoding "URLENCODED") HEADER () BODY ();
CREATE SCHEMASTORE VIEW releases_table WITH CONTAINER pkgtrail AS SELECT r.package AS package_name, r.version, CAST(r.published_at AS TIMESTAMP) AS published_at, r.publisher, CAST(r.removed AS INT) AS removed, r.install_scripts, CAST(r.dep_count AS INT) AS dep_count, r.git_head, r.role FROM pkgtrail_rest.releases_raw LATERAL VIEW explode(rows) AS r;
CREATE SCHEMASTORE VIEW maintainers_table WITH CONTAINER pkgtrail AS SELECT m.package AS package_name, m.version, m.maintainer FROM pkgtrail_rest.maintainers_raw LATERAL VIEW explode(rows) AS m;
CREATE SCHEMASTORE VIEW dependencies_table WITH CONTAINER pkgtrail AS SELECT d.package AS package_name, d.version, d.dependency, d.range AS version_range FROM pkgtrail_rest.dependencies_raw LATERAL VIEW explode(rows) AS d
