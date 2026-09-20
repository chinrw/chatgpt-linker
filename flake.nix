{
  description = "Plan review handoffs to ChatGPT Pro through a constrained MCP outbox";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "aarch64-darwin"
        "x86_64-darwin"
        "aarch64-linux"
        "x86_64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
      pyproject = (builtins.fromTOML (builtins.readFile ./pyproject.toml)).project;
    in
    {
      packages = forAllSystems (pkgs: rec {
        chatgpt-linker = pkgs.python3Packages.buildPythonApplication {
          pname = pyproject.name;
          inherit (pyproject) version;
          pyproject = true;
          src = ./.;
          build-system = [ pkgs.python3Packages.setuptools ];
          nativeCheckInputs = [
            pkgs.python3Packages.unittestCheckHook
            pkgs.git
          ];
          unittestFlagsArray = [
            "-s"
            "tests"
          ];
          meta = {
            description = pyproject.description;
            homepage = "https://github.com/chinrw/chatgpt-linker";
            license = pkgs.lib.licenses.mit;
            mainProgram = "chatgpt-linker";
            platforms = pkgs.lib.platforms.unix;
          };
        };
        default = chatgpt-linker;
      });

      checks = forAllSystems (pkgs: {
        # Building the package runs the unit tests via unittestCheckHook.
        package = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
      });

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            pkgs.python3
            pkgs.uv
          ];
        };
      });
    };
}
