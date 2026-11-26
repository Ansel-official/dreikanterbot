# Dreikanterbot Android 客户端

一个原生 WebView 外壳，加载你部署好的 Dreikanterbot 站点：

- 首次启动填写服务器地址（例如 `https://chat.example.com`）；
- 记住地址，后续直接进入；
- 支持网页文件选择器（对话附件/记忆库上传）；
- 外部链接交给系统浏览器；
- 返回键优先网页后退。

## 构建

要求：JDK 17、Android SDK 34、Gradle 8.7。

```powershell
$env:JAVA_HOME = "E:\toolchain\jdk-17"
$env:ANDROID_HOME = "E:\toolchain\android-sdk"
E:\toolchain\gradle-8.7\bin\gradle.bat -p mobile\android assembleRelease
```

产物：`mobile/android/app/build/outputs/apk/release/app-release.apk`。

当前 `app/build.gradle` 使用本机 Android **debug keystore** 给 release APK 签名，便于侧载测试。
正式上架请替换 `signingConfigs.release` 为你自己的 keystore，并妥善保管。

> APK 只是客户端外壳，模型 Key 和对话数据在服务器上。没有服务器时，先按根目录 README 部署。
