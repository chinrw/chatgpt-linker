{
  lib,
  defaultPackage,
  defaultTunnelPackage,
  defaultExchangeDirectory,
}:
let
  runtimePath = lib.types.addCheck lib.types.str (
    value:
    lib.hasPrefix "/" value
    && value != builtins.storeDir
    && !(lib.hasPrefix "${builtins.storeDir}/" value)
    && !(lib.hasInfix "\n" value)
    && !(lib.hasInfix "\r" value)
  );
in
{
  enable = lib.mkEnableOption "the ChatGPT Linker tunnel user service";
  package = lib.mkOption {
    type = lib.types.package;
    default = defaultPackage;
    defaultText = "The module's ChatGPT Linker package";
    description = "ChatGPT Linker package used by the evidence process.";
  };
  tunnelPackage = lib.mkOption {
    type = lib.types.package;
    default = defaultTunnelPackage;
    defaultText = "The pinned Linux tunnel-client package";
    description = "Tunnel client package. Its executable must support file secret references.";
  };
  tunnelId = lib.mkOption {
    type = lib.types.strMatching "tunnel_[A-Za-z0-9_-]+";
    description = "Existing tunnel ID. This module does not register a tunnel.";
    example = "tunnel_example";
  };
  apiKeyFile = lib.mkOption {
    type = runtimePath;
    description = "Absolute runtime path to a readable API key file outside the Nix store. Never use builtins.readFile here.";
    example = "/run/secrets/linker-tunnel-key";
  };
  exchangeDirectory = lib.mkOption {
    type = runtimePath;
    default = defaultExchangeDirectory;
    description = "Published exchange directory, outside source repositories. Match the CLI state directory's exchange child.";
  };
  healthPort = lib.mkOption {
    type = lib.types.port;
    default = 8080;
    description = "Loopback-only tunnel health and admin port.";
  };
}
