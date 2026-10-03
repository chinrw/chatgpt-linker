{
  lib,
  stdenvNoCC,
  fetchurl,
  unzip,
}:
let
  releases = {
    x86_64-linux = {
      arch = "amd64";
      hash = "sha256-Fb0X6AXK051BIZkRW7nhCpeN01JYoRTN8l3SrmaBx9M=";
    };
    aarch64-linux = {
      arch = "arm64";
      hash = "sha256-LeP7h5oY7bhH4DE1kskS8Zg2hUiCkKf9unrEA+ak+wo=";
    };
  };
  release = releases.${stdenvNoCC.hostPlatform.system};
in
stdenvNoCC.mkDerivation rec {
  pname = "tunnel-client";
  version = "0.0.14";
  src = fetchurl {
    url = "https://github.com/openai/tunnel-client/releases/download/v${version}/tunnel-client-v${version}-linux-${release.arch}.zip";
    inherit (release) hash;
  };
  nativeBuildInputs = [ unzip ];
  sourceRoot = ".";
  dontConfigure = true;
  dontBuild = true;
  dontStrip = true;
  installPhase = ''
    runHook preInstall
    install -Dm755 tunnel-client "$out/bin/tunnel-client"
    # The client locates its pinned companion and manifest beside its executable.
    install -m755 cloudflared "$out/bin/cloudflared"
    install -m644 cloudflared-manifest.json "$out/bin/cloudflared-manifest.json"
    mkdir -p "$out/share/doc/tunnel-client"
    cp LICENSE NOTICE *-licenses.txt *.spdx.json "$out/share/doc/tunnel-client/"
    runHook postInstall
  '';
  meta = {
    description = "OpenAI Secure MCP Tunnel client with its matching companion";
    homepage = "https://github.com/openai/tunnel-client";
    license = [ lib.licenses.asl20 ];
    platforms = builtins.attrNames releases;
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
    mainProgram = "tunnel-client";
  };
}
