# Java 基础入门

## 一、JVM、JRE 与 JDK

JDK 是 Java 开发工具包，包含编译器 `javac`、运行时和各类工具。JRE 是 Java 运行时环境，只包含运行 Java 程序所需的部分。JVM 是 Java 虚拟机，负责执行字节码。

三者的包含关系是：JDK 包含 JRE，JRE 包含 JVM。

Java 源代码经 `javac` 编译为字节码（`.class` 文件），由 JVM 解释执行或即时编译（JIT）为机器码，因此实现“一次编写，到处运行”。

## 二、基本类型与包装类

Java 有八种基本类型：`byte`、`short`、`int`、`long`、`float`、`double`、`char`、`boolean`。`int` 占 4 字节，`long` 占 8 字节。

每种基本类型都有对应的包装类，如 `Integer`、`Double`。自动装箱与拆箱在基本类型和包装类之间自动转换。

需要注意的是，`Integer` 缓存了 -128 到 127 之间的对象，因此该范围内用 `==` 比较两个 `Integer` 可能为 `true`，超出范围则为 `false`。比较包装类应使用 `equals()`。

## 三、面向对象

Java 的三大特性是封装、继承、多态。

类通过 `class` 定义，成员变量默认值：整型为 0，布尔为 false，引用类型为 null。

继承使用 `extends`，Java 只支持单继承。子类构造方法中第一行会隐式调用父类的无参构造，若父类没有无参构造则必须显式 `super(...)`。

`abstract` 抽象类不能实例化，可以包含抽象方法和具体方法。`interface` 接口中的方法默认是 `public abstract`，Java 8 之后允许 `default` 方法。

多态通过父类引用指向子类对象实现，方法调用在运行时动态绑定。

## 四、String

`String` 是不可变对象，每次修改都会产生新对象。频繁拼接应使用 `StringBuilder`，它是可变的且非线程安全；多线程环境用 `StringBuffer`，方法加了 `synchronized`。

字符串常量存放在常量池中，因此 `"abc" == "abc"` 为 `true`，而 `new String("abc") == "abc"` 为 `false`。

## 五、集合框架

`ArrayList` 底层是数组，随机访问 O(1)，中间插入删除 O(n)；`LinkedList` 底层是双向链表，头尾操作快，随机访问慢。

`HashMap` 基于数组加链表（JDK 8 后链表长度超过 8 转为红黑树）实现，平均查找 O(1)。`HashMap` 允许一个 null 键，非线程安全；`Hashtable` 不允许 null 键且线程安全但性能低；`ConcurrentHashMap` 通过分段锁或 CAS 实现高并发。

## 六、异常体系

`Throwable` 是所有异常的根，分为 `Error` 和 `Exception`。`Error` 表示 JVM 层面的严重问题，如 `OutOfMemoryError`，程序通常无法处理。

`Exception` 分为受检异常和非受检异常。受检异常（如 `IOException`）必须显式捕获或声明抛出；非受检异常（`RuntimeException` 及其子类，如 `NullPointerException`）不强制处理。

## 七、多线程基础

创建线程有两种方式：继承 `Thread` 类重写 `run()`，或实现 `Runnable` 接口。推荐后者，因为 Java 单继承限制。

`synchronized` 可以修饰方法或代码块，保证同一时刻只有一个线程进入临界区。`volatile` 保证可见性和禁止指令重排序，但不保证原子性。

## 八、垃圾回收

Java 自动管理内存。常见垃圾回收算法包括标记-清除、复制、标记-整理。现代 JVM 多采用分代收集：新生代用复制算法，老年代用标记-整理或标记-清除。
