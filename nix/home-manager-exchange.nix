{
  config,
  lib,
  pkgs,
  ...
}:
let
  program = config.programs.chatgpt-linker;
  cfg = program.exchange;
  runtimePath = import ./runtime-path.nix { inherit lib; };
  prepare = import ./prepare-exchange.nix {
    inherit lib pkgs;
    inherit (program) exchangeDirectory;
  };
  start = pkgs.writeShellScript "chatgpt-linker-exchange" ''
    exec ${
      lib.escapeShellArgs (
        [
          (lib.getExe program.package)
          "serve-exchange"
          "--exchange"
          program.exchangeDirectory
          "--listen"
          cfg.listen
          "--port"
          (toString cfg.port)
          "--token-file"
          cfg.tokenFile
        ]
        ++ lib.concatMap (host: [
          "--allow-host"
          host
        ]) cfg.allowedHosts
        ++ lib.optionals (cfg.tlsCertFile != null && cfg.tlsKeyFile != null) [
          "--tls-cert"
          cfg.tlsCertFile
          "--tls-key"
          cfg.tlsKeyFile
        ]
      )
    }
  '';
in
{
  options.programs.chatgpt-linker.exchange = {
    enable = lib.mkEnableOption "the ChatGPT Linker task exchange user service";
    listen = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1";
      description = "IPv4 listen address. A non-loopback address requires TLS.";
    };
    port = lib.mkOption {
      type = lib.types.port;
      default = 8767;
      description = "Task exchange port.";
    };
    tokenFile = lib.mkOption {
      type = runtimePath;
      description = "Private runtime bearer token file outside the Nix store.";
    };
    tlsCertFile = lib.mkOption {
      type = lib.types.nullOr runtimePath;
      default = null;
      description = "Runtime PEM certificate file, paired with tlsKeyFile.";
    };
    tlsKeyFile = lib.mkOption {
      type = lib.types.nullOr runtimePath;
      default = null;
      description = "Private runtime PEM key file, paired with tlsCertFile.";
    };
    allowedHosts = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "Accepted Host authorities. Empty uses the listen address and port; a wildcard listener requires explicit hosts.";
    };
  };
  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = program.enable && pkgs.stdenv.hostPlatform.isLinux;
        message = "programs.chatgpt-linker.exchange requires the program to be enabled on Linux.";
      }
      {
        assertion = (cfg.tlsCertFile == null) == (cfg.tlsKeyFile == null);
        message = "chatgpt-linker.exchange requires both tlsCertFile and tlsKeyFile.";
      }
      {
        assertion = lib.hasPrefix "127." cfg.listen || cfg.tlsCertFile != null;
        message = "chatgpt-linker.exchange requires TLS for non-loopback listeners.";
      }
      {
        assertion = cfg.listen != "0.0.0.0" || cfg.allowedHosts != [ ];
        message = "chatgpt-linker.exchange requires allowedHosts for a wildcard listener.";
      }
    ];
    systemd.user.services.chatgpt-linker-exchange = {
      Unit.Description = "ChatGPT Linker task exchange";
      Service = {
        ExecStartPre = "${prepare}";
        ExecStart = "${start}";
        Restart = "on-failure";
        RestartSec = 10;
        UMask = "0077";
      };
      Install.WantedBy = [ "default.target" ];
    };
  };
}
