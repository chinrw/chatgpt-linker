{
  description = "Plan review handoffs to ChatGPT Pro through a constrained MCP outbox";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
  inputs.tunnel-client-nix.url = "github:chinrw/tunnel-client-nix";
  inputs.home-manager = {
    url = "github:nix-community/home-manager";
    inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs =
    {
      self,
      nixpkgs,
      home-manager,
      tunnel-client-nix,
    }:
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
      nixosModules = {
        chatgpt-linker = import ./nix/nixos.nix { inherit self; };
        default = self.nixosModules.chatgpt-linker;
      };
      homeManagerModules = {
        chatgpt-linker = import ./nix/home-manager.nix { inherit self; };
        default = self.homeManagerModules.chatgpt-linker;
      };

      packages = forAllSystems (
        pkgs:
        rec {
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
        }
        // pkgs.lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
          tunnel-client = tunnel-client-nix.packages.${pkgs.stdenv.hostPlatform.system}.tunnel-client;
        }
      );

      checks = forAllSystems (
        pkgs:
        {
          # Building the package runs the unit tests via unittestCheckHook.
          package = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
        }
        // pkgs.lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
          tunnel-modules = import ./nix/tests.nix {
            inherit
              self
              nixpkgs
              home-manager
              pkgs
              ;
          };
          tunnel-package = pkgs.runCommand "tunnel-client-smoke" { } ''
            ${self.packages.${pkgs.stdenv.hostPlatform.system}.tunnel-client}/bin/tunnel-client --version
            test -f ${
              self.packages.${pkgs.stdenv.hostPlatform.system}.tunnel-client
            }/libexec/tunnel-client/cloudflared-manifest.json
            touch "$out"
          '';
        }
      );

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
