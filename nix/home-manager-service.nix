{ self }:
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.chatgpt-linker;
in
{
  options.services.chatgpt-linker = import ./tunnel-options.nix {
    inherit lib;
    defaultPackage = config.programs.chatgpt-linker.package;
    defaultTunnelPackage = pkgs.callPackage ./tunnel-client.nix { };
    defaultExchangeDirectory = "${config.xdg.stateHome}/chatgpt-linker/exchange";
  };
  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = pkgs.stdenv.hostPlatform.isLinux;
        message = "The ChatGPT Linker tunnel user service requires Linux.";
      }
    ];
    systemd.user.services.chatgpt-linker = {
      Unit.Description = "ChatGPT Linker tunnel";
      Service = import ./tunnel-service.nix { inherit lib pkgs cfg; };
      Install.WantedBy = [ "default.target" ];
    };
  };
}
