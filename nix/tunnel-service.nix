{
  lib,
  pkgs,
  cfg,
}:
let
  mcp = pkgs.writeShellScript "chatgpt-linker-mcp" ''
    # The evidence process must not inherit the tunnel's credential environment.
    exec ${lib.getExe' pkgs.coreutils "env"} -i HOME="$RUNTIME_DIRECTORY" \
      ${lib.getExe cfg.package} serve --exchange ${lib.escapeShellArg cfg.exchangeDirectory}
  '';
  start = pkgs.writeShellScript "chatgpt-linker-tunnel" ''
    if ! test -f ${lib.escapeShellArg cfg.apiKeyFile} || ! test -s ${lib.escapeShellArg cfg.apiKeyFile} || ! test -r ${lib.escapeShellArg cfg.apiKeyFile}; then
      echo 'ChatGPT Linker tunnel API key file is not readable.' >&2
      exit 1
    fi
    exec ${lib.getExe cfg.tunnelPackage} run \
      --control-plane.tunnel-id ${lib.escapeShellArg cfg.tunnelId} \
      --control-plane.api-key ${lib.escapeShellArg "file:${cfg.apiKeyFile}"} \
      --health.listen-addr ${lib.escapeShellArg "127.0.0.1:${toString cfg.healthPort}"} \
      --mcp.command ${lib.escapeShellArg "command=${mcp},channel=main"}
  '';
  prepare = pkgs.writeShellScript "chatgpt-linker-prepare-exchange" ''
    exec ${lib.getExe' pkgs.coreutils "install"} -d -m 0700 \
      ${lib.escapeShellArgs [
        cfg.exchangeDirectory
        "${cfg.exchangeDirectory}/inbox"
        "${cfg.exchangeDirectory}/outbox"
      ]}
  '';
in
{
  ExecStartPre = "${prepare}";
  ExecStart = "${start}";
  Restart = "on-failure";
  RestartSec = 10;
  RuntimeDirectory = "chatgpt-linker";
  RuntimeDirectoryMode = "0700";
  UMask = "0077";
}
