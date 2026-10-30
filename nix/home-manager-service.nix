{ self }:
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.programs.chatgpt-linker.tunnel;
  program = config.programs.chatgpt-linker;
  tunnelOptions = import ./tunnel-options.nix {
    inherit lib;
    defaultPackage = program.package;
    defaultTunnelPackage = self.packages.${pkgs.stdenv.hostPlatform.system}.tunnel-client;
    defaultExchangeDirectory = "${config.xdg.stateHome}/chatgpt-linker/exchange";
  };
in
{
  imports = [
    ./home-manager-exchange.nix
    (lib.mkRenamedOptionModule [ "services" "chatgpt-linker" ] [ "programs" "chatgpt-linker" "tunnel" ])
    (lib.mkAliasOptionModule
      [ "programs" "chatgpt-linker" "tunnel" "exchangeDirectory" ]
      [ "programs" "chatgpt-linker" "exchangeDirectory" ]
    )
  ];
  options.programs.chatgpt-linker = {
    inherit (tunnelOptions) exchangeDirectory;
    tunnel = builtins.removeAttrs tunnelOptions [ "exchangeDirectory" ];
  };
  config = lib.mkMerge [
    (lib.mkIf cfg.enable {
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
    })
    (lib.mkIf (cfg.enable || program.exchange.enable) {
      # install -d creates intermediate directories with 0755, but the local CLI
      # requires its state root to be private before either service starts.
      home.activation.chatgptLinkerState =
        lib.hm.dag.entryBetween [ "reloadSystemd" ] [ "writeBoundary" ]
          ''
            run ${pkgs.coreutils}/bin/install -d -m 0700 ${lib.escapeShellArg "${config.xdg.stateHome}/chatgpt-linker"}
          '';
    })
  ];
}
