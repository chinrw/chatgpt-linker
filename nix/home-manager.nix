{ self }:
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.programs.chatgpt-linker;
  skillName = "ultraplan";
  skillSource = ../skills + "/${skillName}";
  skillDirectories = {
    agents = ".agents/skills";
    claude = ".claude/skills";
  };
in
{
  options.programs.chatgpt-linker = {
    enable = lib.mkEnableOption "ChatGPT Linker and its ultraplan skill";

    package = lib.mkOption {
      type = lib.types.package;
      default = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
      defaultText = lib.literalExpression "inputs.chatgpt-linker.packages.\${system}.default";
      description = "The ChatGPT Linker CLI package to install.";
    };

    skillTargets = lib.mkOption {
      type = lib.types.listOf (lib.types.enum (builtins.attrNames skillDirectories));
      default = [
        "agents"
        "claude"
      ];
      example = [ "agents" ];
      description = ''
        Install ultraplan in the shared agent directory and/or Claude Code's
        directory. An empty list installs only the CLI.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = builtins.pathExists (skillSource + "/SKILL.md");
        message = "chatgpt-linker: the ultraplan skill is missing from this flake source.";
      }
    ];

    home.packages = [ cfg.package ];
    home.file = lib.genAttrs (
      map (target: "${skillDirectories.${target}}/${skillName}") (lib.unique cfg.skillTargets)
    ) (_: {
      source = skillSource;
    });
  };
}
