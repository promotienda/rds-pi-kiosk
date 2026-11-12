The open-source runtime dependencies of the RDS agent (rds-agent .deb
"Depends", release 2.1.2, plus the two that tauri-bundler adds), installed in
advance so that "Pair with RDS" only has to download the agent itself
(a few MB) instead of ~150 MB of packages. The agent is NOT in the image:
it is downloaded from RDS when the user chooses to pair. Delete this
directory to build an image without them; pairing then takes longer.
