{
  self,
  nixpkgs,
  home-manager,
  pkgs,
}:
let
  inherit (pkgs) lib;
  directory = "/tmp/chatgpt-linker-module-test";
  mockTunnel = pkgs.writeScriptBin "tunnel-client" ''
    #!${pkgs.python3}/bin/python3
    import json, os, subprocess, sys
    args = sys.argv[1:]
    assert args[0] == "run"
    assert args[args.index("--control-plane.api-key") + 1] == "file:${directory}/api key"
    assert args[args.index("--control-plane.tunnel-id") + 1] == "tunnel_fixture"
    assert args[args.index("--health.listen-addr") + 1] == "127.0.0.1:8080"
    command = args[args.index("--mcp.command") + 1]
    assert command.endswith(",channel=main")
    launcher = command.removeprefix("command=").removesuffix(",channel=main")
    if os.environ.get("TEST_REAL_LINKER"):
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-11-25", "capabilities": {},
                "clientInfo": {"name": "nix-test", "version": "1"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ]
        result = subprocess.run([launcher], input="".join(json.dumps(m) + "\n" for m in messages),
                                capture_output=True, text=True, timeout=15, check=True)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        assert all("error" not in r for r in responses)
        tools = next(r["result"]["tools"] for r in responses if r.get("id") == 2)
        assert {t["name"] for t in tools} == {"search", "fetch", "submit_review"}
    else:
        data = json.loads(subprocess.check_output([launcher], text=True))
        assert data["args"] == ["serve", "--exchange", "${directory}/exchange with spaces"]
        assert data["home"] == os.environ["RUNTIME_DIRECTORY"]
        assert not data["inherited_secret"]
    with open("${directory}/api key") as stream:
        assert stream.read() == os.environ["EXPECTED_KEY"]
    print("runtime arguments and clean child environment passed")
  '';
  mockLinker = pkgs.writeScriptBin "chatgpt-linker" ''
    #!${pkgs.python3}/bin/python3
    import json, os, sys
    print(json.dumps({"args": sys.argv[1:], "home": os.environ.get("HOME"),
      "inherited_secret": any(k in os.environ for k in ["CONTROL_PLANE_API_KEY", "OPENAI_API_KEY", "OTHER_SECRET"])}))
  '';
  settings = {
    enable = true;
    package = mockLinker;
    tunnelPackage = mockTunnel;
    tunnelId = "tunnel_fixture";
    apiKeyFile = "${directory}/api key";
    exchangeDirectory = "${directory}/exchange with spaces";
  };
  nixos =
    extra:
    nixpkgs.lib.nixosSystem {
      system = pkgs.stdenv.hostPlatform.system;
      modules = [
        self.nixosModules.default
        {
          boot.isContainer = true;
          system.stateVersion = "26.05";
          users.users.alice = {
            isNormalUser = true;
            uid = 1000;
          };
          services.chatgpt-linker = settings // {
            user = "alice";
          };
        }
        extra
      ];
    };
  os = nixos { };
  mkHome =
    extra:
    home-manager.lib.homeManagerConfiguration {
      inherit pkgs;
      modules = [
        self.homeManagerModules.default
        {
          home.username = "alice";
          home.homeDirectory = "/home/alice";
          home.stateVersion = "26.05";
          programs.chatgpt-linker.enable = true;
        }
        extra
      ];
    };
  hm = mkHome { programs.chatgpt-linker.tunnel = settings; };
  cliOnly = mkHome { };
  tunnelOnly = mkHome {
    programs.chatgpt-linker = {
      enable = lib.mkForce false;
      tunnel = settings;
    };
  };
  off = nixpkgs.lib.nixosSystem {
    system = pkgs.stdenv.hostPlatform.system;
    modules = [
      self.nixosModules.default
      { system.stateVersion = "26.05"; }
    ];
  };
  invalid = nixos { services.chatgpt-linker.apiKeyFile = lib.mkForce "/nix/store/plaintext-key"; };
  rootUser = nixos { services.chatgpt-linker.user = lib.mkForce "root"; };
  absentUser = nixos { services.chatgpt-linker.user = lib.mkForce "absent"; };
  rootAlias = nixos {
    users.users.root-alias = {
      isSystemUser = true;
      uid = 0;
      group = "users";
    };
    services.chatgpt-linker.user = lib.mkForce "root-alias";
  };
  service = os.config.systemd.user.services.chatgpt-linker.serviceConfig;
  realService = import ./tunnel-service.nix {
    inherit lib pkgs;
    cfg = hm.config.programs.chatgpt-linker.tunnel // {
      package = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
    };
  };
in
assert !(cliOnly.config.systemd.user.services ? chatgpt-linker);
assert !(builtins.tryEval tunnelOnly.activationPackage.drvPath).success;
assert os.config.users.users.alice.linger;
assert os.config.systemd.user.services.chatgpt-linker.unitConfig.ConditionUser == "alice";
assert !(off.config.systemd.user.services ? chatgpt-linker);
assert lib.assertMsg
  (lib.all (
    key:
    toString service.${key} == toString hm.config.systemd.user.services.chatgpt-linker.Service.${key}
  ) (builtins.attrNames service))
  (
    builtins.toJSON {
      nixos = service;
      home = hm.config.systemd.user.services.chatgpt-linker.Service;
    }
  );
assert
  !(builtins.tryEval (
    builtins.deepSeq invalid.config.systemd.user.services.chatgpt-linker.serviceConfig true
  )).success;
assert lib.any (
  a: !a.assertion && lib.hasInfix "existing non-root" a.message
) rootUser.config.assertions;
assert lib.any (
  a: !a.assertion && lib.hasInfix "existing non-root" a.message
) absentUser.config.assertions;
assert lib.any (
  a: !a.assertion && lib.hasInfix "existing non-root" a.message
) rootAlias.config.assertions;
pkgs.runCommand "chatgpt-linker-tunnel-modules"
  {
    nativeBuildInputs = [ pkgs.python3 ];
  }
  ''
    test ! -e ${lib.escapeShellArg directory}
    mkdir -m 0700 ${lib.escapeShellArg directory}
    trap 'rm -rf ${directory}' EXIT
    export RUNTIME_DIRECTORY=${directory}/runtime
    mkdir -m 0700 "$RUNTIME_DIRECTORY"
    export CONTROL_PLANE_API_KEY=synthetic-env-key OPENAI_API_KEY=synthetic-fallback OTHER_SECRET=synthetic-other
    ${service.ExecStartPre}
    test "$(stat -c %a '${directory}/exchange with spaces')" = 700
    test "$(stat -c %a '${directory}/exchange with spaces/inbox')" = 700
    if ${service.ExecStart} >missing.log 2>&1; then
      echo 'Missing runtime credential was accepted' >&2
      exit 1
    fi
    export EXPECTED_KEY=synthetic-first-key
    printf %s "$EXPECTED_KEY" > '${directory}/api key'
    chmod 600 '${directory}/api key'
    ${service.ExecStart}
    export EXPECTED_KEY=synthetic-rotated-key
    printf %s "$EXPECTED_KEY" > '${directory}/api key'
    ${service.ExecStart}
    TEST_REAL_LINKER=1 ${realService.ExecStart}
    touch "$out"
  ''
