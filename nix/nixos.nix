{ self }:
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.chatgpt-linker;
  userHome = config.users.users.${cfg.user}.home or "/var/empty";
in
{
  options.services.chatgpt-linker =
    (import ./tunnel-options.nix {
      inherit lib;
      defaultPackage = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
      defaultTunnelPackage = pkgs.callPackage ./tunnel-client.nix { };
      defaultExchangeDirectory = "${userHome}/.local/state/chatgpt-linker/exchange";
    })
    // {
      user = lib.mkOption {
        type = lib.types.str;
        default = "";
        description = "Existing non-root account that owns the exchange and can read the API key.";
        example = "alice";
      };
    };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion =
          cfg.user != ""
          && cfg.user != "root"
          && (config.users.users.${cfg.user}.uid or null) != 0
          && (
            (config.users.users.${cfg.user}.isNormalUser or false)
            || (config.users.users.${cfg.user}.isSystemUser or false)
          );
        message = "services.chatgpt-linker.user must name an existing non-root account.";
      }
    ];
    users.users = lib.mkIf (cfg.user != "") {
      ${cfg.user}.linger = true;
    };
    systemd.user.services.chatgpt-linker = {
      description = "ChatGPT Linker tunnel";
      wantedBy = [ "default.target" ];
      # NixOS installs user units for every account, but only this account owns the tunnel.
      unitConfig.ConditionUser = cfg.user;
      serviceConfig = import ./tunnel-service.nix { inherit lib pkgs cfg; };
    };
  };
}
