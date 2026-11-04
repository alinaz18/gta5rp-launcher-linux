Name:           gta5rp-launcher
Version:        %{pkg_version}
Release:        1%{?dist}
Summary:        Unofficial GTA5RP (RAGE:MP) launcher for Linux
License:        MIT
URL:            https://github.com/alinaz18/gta5rp-launcher-linux
Source0:        gta5rp-launcher-%{version}.tar.gz
BuildArch:      noarch

Requires:       python3 >= 3.9
Requires:       python3-pyside6
Recommends:     steam
Recommends:     wine
Suggests:       p7zip

%description
Native Qt launcher for the GTA5RP roleplay project: account login, server list
with online counters, news, and one-click start of RAGE:MP. The game runs
through Steam's Proton in the GTA V prefix. Not affiliated with GTA5RP.

%prep
%setup -q

%build

%install
bash packaging/stage.sh %{buildroot} %{_prefix}

%files
%license %{_datadir}/licenses/gta5rp-launcher/LICENSE
%doc %{_datadir}/doc/gta5rp-launcher/README.md
%doc %{_datadir}/doc/gta5rp-launcher/README.en.md
%{_bindir}/gta5rp-launcher
%{_datadir}/gta5rp-launcher/
%{_datadir}/applications/gta5rp-launcher.desktop
%{_datadir}/icons/hicolor/scalable/apps/gta5rp-launcher.svg
