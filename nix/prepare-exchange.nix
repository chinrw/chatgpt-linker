{
  lib,
  pkgs,
  exchangeDirectory,
}:
pkgs.writeShellScript "chatgpt-linker-prepare-exchange" ''
  exec ${lib.getExe' pkgs.coreutils "install"} -d -m 0700 \
    ${lib.escapeShellArgs [
      exchangeDirectory
      "${exchangeDirectory}/inbox"
      "${exchangeDirectory}/outbox"
    ]}
''
