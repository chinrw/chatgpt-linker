{ self }:
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.programs.chatgpt-linker.tunnel;
in
{
  imports = [
    (lib.mkRenamedOptionModule [ "services" "chatgpt-linker" ] [ "programs" "chatgpt-linker" "tunnel" ])
  ];
  options.programs.chatgpt-linker.tunnel = import ./tunnel-options.nix {
    inherit lib;
    defaultPackage = config.programs.chatgpt-linker.package;
    defaultTunnelPackage = self.packages.${pkgs.stdenv.hostPlatform.system}.tunnel-client;
    defaultExchangeDirectory = "${config.xdg.stateHome}/chatgpt-linker/exchange";
  };
  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = config.programs.chatgpt-linker.enable;
        message = "programs.chatgpt-linker.tunnel requires programs.chatgpt-linker.enable.";
      }
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
