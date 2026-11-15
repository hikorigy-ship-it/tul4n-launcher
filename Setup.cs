using System;
using System.IO;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Diagnostics;
using System.Net;
using System.Security.Cryptography;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Reflection;

[assembly: AssemblyTitle("TUL4N Лаунчер — интернет-установщик")]
[assembly: AssemblyProduct("TUL4N Лаунчер")]
[assembly: AssemblyVersion("1.0.0.0")]

static class Installation
{
    public static string Digest(string path)
    {
        using (var sha=SHA256.Create()) using(var input=File.OpenRead(path))
            return BitConverter.ToString(sha.ComputeHash(input)).Replace("-", "").ToLowerInvariant();
    }
    public static void Shortcut(string folder,string exe)
    {
        Directory.CreateDirectory(folder);
        var type=Type.GetTypeFromProgID("WScript.Shell");
        dynamic shell=Activator.CreateInstance(type);
        dynamic shortcut=shell.CreateShortcut(Path.Combine(folder,"TUL4N Лаунчер.lnk"));
        shortcut.TargetPath=exe;shortcut.WorkingDirectory=Path.GetDirectoryName(exe);
        shortcut.IconLocation=exe+",0";shortcut.Description="TUL4N Лаунчер • Minecraft";shortcut.Save();
    }
    public static async Task<string> Install(string folder,bool desktop,bool menu,Action<int,string> progress)
    {
        string target=Path.GetFullPath(folder.Trim());
        if(target.TrimEnd(Path.DirectorySeparatorChar).Length<4 || target.StartsWith(Environment.GetFolderPath(Environment.SpecialFolder.Windows),StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Выберите отдельную папку для лаунчера.");
        Directory.CreateDirectory(target);
        string staging=Path.Combine(target,".tul4n-install-"+Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(staging);
        string downloaded=Path.Combine(staging,"TUL4N.exe");
        try
        {
            ServicePointManager.SecurityProtocol=SecurityProtocolType.Tls12;
            using(var client=new WebClient())
            {
                client.Headers[HttpRequestHeader.UserAgent]="TUL4N-Setup/1.0";
                client.DownloadProgressChanged+=(s,e)=>progress(Math.Min(90,e.ProgressPercentage*9/10),"Скачиваем лаунчер… "+(e.BytesReceived/1048576.0).ToString("0.0")+" МБ");
                await client.DownloadFileTaskAsync(new Uri(ReleaseInfo.DownloadUrl),downloaded);
            }
            progress(92,"Проверяем целостность файла…");
            string hash=await Task.Run(()=>Digest(downloaded));
            if(!String.Equals(hash,ReleaseInfo.Sha256,StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Не совпала контрольная сумма файла. Установка отменена. Повторите загрузку с официальной страницы TUL4N.");
            string exe=Path.Combine(target,"TUL4N.exe");
            progress(96,"Устанавливаем TUL4N Лаунчер…");
            if(File.Exists(exe)) File.Replace(downloaded,exe,Path.Combine(target,"TUL4N.previous.exe"),true);
            else File.Move(downloaded,exe);
            if(desktop)Shortcut(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),exe);
            if(menu)Shortcut(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs),"TUL4N Лаунчер"),exe);
            progress(100,"TUL4N Лаунчер установлен!");
            return exe;
        }
        finally
        {
            // This uniquely created staging directory contains only this download.
            if(Directory.Exists(staging) && Path.GetDirectoryName(staging)==target && Path.GetFileName(staging).StartsWith(".tul4n-install-"))
                try{Directory.Delete(staging,true);}catch{}
        }
    }
}

class Banner:Panel
{
    public Banner(){DoubleBuffered=true;Height=150;Dock=DockStyle.Top;}
    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e); e.Graphics.SmoothingMode=SmoothingMode.AntiAlias;
        using(var brush=new LinearGradientBrush(ClientRectangle,Color.FromArgb(43,28,76),Color.FromArgb(91,53,177),30f))e.Graphics.FillRectangle(brush,ClientRectangle);
        using(var brush=new SolidBrush(Color.FromArgb(170,133,255)))e.Graphics.FillPolygon(brush,new[]{new Point(510,28),new Point(555,113),new Point(474,113)});
        using(var brush=new SolidBrush(Color.FromArgb(112,67,205)))e.Graphics.FillPolygon(brush,new[]{new Point(510,28),new Point(555,113),new Point(510,102)});
        using(var font=new Font("Segoe UI",27,FontStyle.Bold)) e.Graphics.DrawString("TUL4N",font,Brushes.White,new PointF(28,28));
        using(var font=new Font("Segoe UI",12)) e.Graphics.DrawString("Твой следующий мир — в один клик",font,Brushes.Lavender,new PointF(30,84));
    }
}

class SetupWindow:Form
{
    TextBox path;Button browse,install;Label status;ProgressBar bar;CheckBox desktop,launch;
    bool running=false;string installed=null;
    public SetupWindow()
    {
        Text="TUL4N Лаунчер — установка";ClientSize=new Size(620,490);MinimumSize=MaximumSize=Size;
        FormBorderStyle=FormBorderStyle.FixedSingle;MaximizeBox=false;StartPosition=FormStartPosition.CenterScreen;
        Font=new Font("Segoe UI",10);BackColor=Color.FromArgb(20,18,26);ForeColor=Color.FromArgb(234,226,247);
        Icon=Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        Controls.Add(new Banner());
        var heading=new Label{Text="Установить TUL4N Лаунчер",Location=new Point(28,172),Size=new Size(550,32),Font=new Font("Segoe UI",17,FontStyle.Bold)};Controls.Add(heading);
        Controls.Add(new Label{Text="Программа загрузится из интернета. Аккаунты и миры сохраняются.",Location=new Point(30,213),Size=new Size(560,24),ForeColor=Color.FromArgb(163,152,179)});
        path=new TextBox{Location=new Point(30,252),Size=new Size(445,28),BackColor=Color.FromArgb(39,33,48),ForeColor=ForeColor,BorderStyle=BorderStyle.FixedSingle,Text=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","TUL4N")};Controls.Add(path);
        browse=new Button{Text="Обзор…",Location=new Point(486,249),Size=new Size(104,32),FlatStyle=FlatStyle.Flat};browse.Click+=(s,e)=>{using(var dialog=new FolderBrowserDialog()){dialog.Description="Папка установки TUL4N Лаунчера";dialog.SelectedPath=path.Text;if(dialog.ShowDialog()==DialogResult.OK)path.Text=dialog.SelectedPath;}};Controls.Add(browse);
        desktop=new CheckBox{Text="Создать ярлык на рабочем столе",Checked=true,Location=new Point(30,298),Size=new Size(550,25)};Controls.Add(desktop);
        launch=new CheckBox{Text="Открыть лаунчер после установки",Checked=true,Location=new Point(30,329),Size=new Size(550,25)};Controls.Add(launch);
        bar=new ProgressBar{Location=new Point(30,371),Size=new Size(560,7),Maximum=100,Style=ProgressBarStyle.Continuous};Controls.Add(bar);
        status=new Label{Text="Готово к установке • Windows 10 / 11 x64",Location=new Point(30,390),Size=new Size(560,33),ForeColor=Color.FromArgb(176,158,202)};Controls.Add(status);
        install=new Button{Text="Установить",Location=new Point(397,435),Size=new Size(193,37),BackColor=Color.FromArgb(112,72,235),ForeColor=Color.White,FlatStyle=FlatStyle.Flat};install.FlatAppearance.BorderSize=0;install.Click+=InstallClicked;Controls.Add(install);
        Controls.Add(new Label{Text="Без установки Python",Location=new Point(30,443),Size=new Size(300,25),ForeColor=Color.FromArgb(132,121,148)});
        FormClosing+=(s,e)=>{if(running){e.Cancel=true;status.Text="Дождитесь окончания загрузки.";}};
    }
    void Progress(int value,string text)
    {
        if(IsDisposed)return;
        if(InvokeRequired){BeginInvoke(new Action(()=>Progress(value,text)));return;}
        bar.Value=Math.Max(0,Math.Min(100,value));status.Text=text;
    }
    async void InstallClicked(object sender,EventArgs e)
    {
        if(installed!=null){Close();return;}
        if(!Environment.Is64BitOperatingSystem){MessageBox.Show("Для Minecraft и этого лаунчера нужна 64-разрядная Windows 10 или новее.");return;}
        running=true;install.Enabled=browse.Enabled=path.Enabled=desktop.Enabled=launch.Enabled=false;
        try
        {
            installed=await Installation.Install(path.Text,desktop.Checked,true,Progress);
            install.Text="Готово";
            if(launch.Checked)Process.Start(new ProcessStartInfo(installed){WorkingDirectory=Path.GetDirectoryName(installed),UseShellExecute=true});
        }
        catch(Exception error)
        {
            status.Text="Установка не завершена. Можно повторить.";
            MessageBox.Show("Не удалось установить лаунчер. Проверьте интернет, доступ к папке и закройте запущенный TUL4N.\n\n"+error.Message,"TUL4N",MessageBoxButtons.OK,MessageBoxIcon.Information);
        }
        finally{running=false;install.Enabled=true;if(installed==null)browse.Enabled=path.Enabled=desktop.Enabled=launch.Enabled=true;}
    }
}

static class Program
{
    [STAThread]static int Main(string[] args)
    {
        if(args.Length==2 && args[0]=="--test-install")
        {
            try{Installation.Install(args[1],false,false,(p,s)=>{}).GetAwaiter().GetResult();return 0;}catch{return 1;}
        }
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);Application.Run(new SetupWindow());return 0;
    }
}

