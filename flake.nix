{
  description = "CVM and MANTIS";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    rust-overlay = {
      url = "github:oxalica/rust-overlay";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    crane = {
      url = "github:ipetkov/crane";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    cosmos = {
      url = "github:informalsystems/cosmos.nix";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.rust-overlay.follows = "rust-overlay";
    };

    devour-flake = {
      url = "github:srid/devour-flake";
      flake = false;
    };
  };

  outputs = inputs @ {
    flake-parts,
    self,
    crane,
    devour-flake,
    ...
  }:
    flake-parts.lib.mkFlake {inherit inputs;} {
      imports = [
      ];

      systems = ["x86_64-linux" "aarch64-linux" "aarch64-darwin" "x86_64-darwin"];
      perSystem = {
        config,
        self',
        inputs',
        pkgs,
        system,
        ...
      }: let
        craneLib = crane.lib.${system};
        rust-src = pkgs.lib.cleanSourceWith {
          filter = pkgs.nix-gitignore.gitignoreFilterPure (name: _type: !(pkgs.lib.strings.hasSuffix ".nix" name)) [./.gitignore] ./.;
          src = craneLib.cleanCargoSource (craneLib.path ./.);
        };
        devour-flake = pkgs.callPackage inputs.devour-flake {};
        rust-toolchain =
          pkgs.rust-bin.fromRustupToolchainFile ./rust-toolchain.toml;
        rust =
          (self.inputs.crane.mkLib pkgs).overrideToolchain
          rust-toolchain;
        makeCosmwasmContract = name: rust: std-config: let
          binaryName = "${builtins.replaceStrings ["-"] ["_"] name}.wasm";
        in
          rust.buildPackage {
            src = rust-src;
            pnameSuffix = "-${name}";
            nativeBuildInputs = [
              pkgs.binaryen
              self.inputs.cosmos.packages.${system}.cosmwasm-check
            ];
            pname = name;
            cargoBuildCommand = "cargo build --target wasm32-unknown-unknown --profile release --package ${name} ${std-config}";
            RUSTFLAGS = "-C link-arg=-s";
            installPhaseCommand = ''
              mkdir --parents $out/lib
              # from CosmWasm/rust-optimizer
              # --signext-lowering is needed to support blockchains runnning CosmWasm < 1.3. It can be removed eventually
              wasm-opt target/wasm32-unknown-unknown/release/${binaryName} -o $out/lib/${binaryName} -Os --signext-lowering
              cosmwasm-check $out/lib/${binaryName}
            '';
          };

        cw-mantis-order = makeCosmwasmContract "cw-mantis-order" rust "--no-default-features";
      in {
        _module.args.pkgs = import self.inputs.nixpkgs {
          inherit system;
          overlays = with self.inputs; [
            rust-overlay.overlays.default
          ];
        };
        devShells.default = let
          python-packages = ps: with ps; [numpy cvxpy wheel virtualenv];
          python = pkgs.python3.withPackages python-packages;
        in
          pkgs.mkShell {
            VIRTUALENV_PYTHON = "${python}/bin/python3.11";
            VIRTUAL_ENV = 1;
            nativeBuildInputs = [python];
            buildInputs = [
              python
              devour-flake
              pkgs.virtualenv
              pkgs.conda
              pkgs.pyo3-pack
              rust.cargo
              rust.rustc
              devour-flake
            ];
          };
        formatter = pkgs.alejandra;
        packages = rec {
          inherit cw-mantis-order;
          mantis-node = rust.buildPackage {
            src = rust-src;
            pname = "mantis-node";
            name = "mantis-node";
            cargoBuildCommand = "cargo build --release --package mantis-node --bin mantis";
          };
          default = mantis-node;
          ci = pkgs.writeShellApplication {
            name = "nix-build-all";
            runtimeInputs = [
              pkgs.nix
              devour-flake
            ];
            text = ''
              nix flake lock --no-update-lock-file
              devour-flake . "$@"
            '';
          };
        };
      };
    };
}
