{ pkgs }: {
  deps = [
    pkgs.python310Full
    pkgs.stdenv.cc.cc.lib
  ];
  env = {
    LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib ];
  };
}
