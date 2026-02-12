
[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  UserDataPath: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    if MsgBox('是否同时删除所有个人数据（配置文件、数据库、收藏等）？' #13#10 '如果您计划重新安装，建议选择“否”保留数据。' #13#10 '选择“是”将彻底删除包括数据库在内的所有用户数据。', mbConfirmation, MB_YESNO) = IDYES then
    begin
      // 1. Get UserDataPath from Registry (HKCU usually)
      if RegQueryStringValue(HKCU, 'Software\BirdPictureManager\BirdManager_Global', 'UserDataPath', UserDataPath) then
      begin
        if (UserDataPath <> '') and DirExists(UserDataPath) then
        begin
           DelTree(UserDataPath, True, True, True);
        end;
      end;
      
      // Also try default path: Documents/qitu/data
      UserDataPath := ExpandConstant('{userdocs}\qitu\data');
      if DirExists(UserDataPath) then
      begin
         DelTree(UserDataPath, True, True, True);
      end;

      // 2. Delete Registry Keys
      if RegKeyExists(HKCU, 'Software\BirdPictureManager') then
      begin
        RegDeleteKeyIncludingSubkeys(HKCU, 'Software\BirdPictureManager');
      end;
    end;
  end;
end;
