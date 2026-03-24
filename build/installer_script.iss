
[Code]
var
  DeleteUserDataCheckBox: TNewCheckBox;
  DeleteUserDataPage: TWizardPage;

// 创建卸载时的自定义页面
procedure InitializeUninstallProgressForm();
var
  Page: TNewNotebookPage;
  PageText: TNewStaticText;
begin
  // 在卸载进度页面之前创建自定义页面
  DeleteUserDataPage := CreateCustomPage(wpUninstalling, '删除用户数据', '选择是否删除用户配置文件和数据');

  // 添加说明文字
  PageText := TNewStaticText.Create(DeleteUserDataPage);
  PageText.Parent := DeleteUserDataPage.Surface;
  PageText.Left := 0;
  PageText.Top := 0;
  PageText.Width := DeleteUserDataPage.SurfaceWidth;
  PageText.Height := 60;
  PageText.Caption := '您可以选择在卸载时是否删除用户配置文件和数据。' + #13#10 +
                      #13#10 +
                      '包括：数据库、配置文件、缓存、收藏记录等个人数据。' + #13#10 +
                      '如果您计划重新安装软件，建议保留这些数据。';
  PageText.WordWrap := True;

  // 创建复选框（默认不勾选）
  DeleteUserDataCheckBox := TNewCheckBox.Create(DeleteUserDataPage);
  DeleteUserDataCheckBox.Parent := DeleteUserDataPage.Surface;
  DeleteUserDataCheckBox.Left := 0;
  DeleteUserDataCheckBox.Top := 70;
  DeleteUserDataCheckBox.Width := DeleteUserDataPage.SurfaceWidth;
  DeleteUserDataCheckBox.Height := 20;
  DeleteUserDataCheckBox.Caption := '删除所有用户数据（配置文件、数据库等）';
  DeleteUserDataCheckBox.Checked := False; // 默认不勾选
end;

// 卸载步骤变化时的处理
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  UserDataPath: String;
begin
  // 在卸载完成后执行删除操作
  if CurUninstallStep = usPostUninstall then
  begin
    // 检查用户是否勾选了删除数据选项
    if (DeleteUserDataCheckBox <> nil) and DeleteUserDataCheckBox.Checked then
    begin
      // 1. 从注册表获取 UserDataPath
      if RegQueryStringValue(HKCU, 'Software\BirdPictureManager\BirdManager_Global', 'UserDataPath', UserDataPath) then
      begin
        if (UserDataPath <> '') and DirExists(UserDataPath) then
        begin
           DelTree(UserDataPath, True, True, True);
        end;
      end;

      // 2. 同时尝试默认路径: Documents/qitu/data
      UserDataPath := ExpandConstant('{userdocs}\qitu\data');
      if DirExists(UserDataPath) then
      begin
         DelTree(UserDataPath, True, True, True);
      end;

      // 3. 尝试其他可能的配置路径
      UserDataPath := ExpandConstant('{localappdata}\qitu');
      if DirExists(UserDataPath) then
      begin
         DelTree(UserDataPath, True, True, True);
      end;

      // 4. 删除注册表项
      if RegKeyExists(HKCU, 'Software\BirdPictureManager') then
      begin
        RegDeleteKeyIncludingSubkeys(HKCU, 'Software\BirdPictureManager');
      end;

      // 5. 删除程序目录下的 cache 和 update 目录
      UserDataPath := ExpandConstant('{app}\cache');
      if DirExists(UserDataPath) then
      begin
         DelTree(UserDataPath, True, True, True);
      end;

      UserDataPath := ExpandConstant('{app}\update');
      if DirExists(UserDataPath) then
      begin
         DelTree(UserDataPath, True, True, True);
      end;
    end;
  end;
end;
